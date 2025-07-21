# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from typing import Any, Dict, List, Tuple, Optional
from logging import getLogger
from pprint import pformat

import osc.conf
import osc.core

from openqabot.openqa import openQAInterface

from . import OBS_GROUP, OBS_URL

log = getLogger("bot.increment_approver")
ok_results = set(("passed", "softfailed"))
final_states = set(("done", "cancelled"))


class IncrementApprover:
    def __init__(self, args: Namespace) -> None:
        self.args = args
        self.token = {"Authorization": "Token {}".format(args.token)}
        self.client = openQAInterface(args)
        osc.conf.get_config(override_apiurl=OBS_URL)

    def _find_request_on_obs(self) -> Optional[osc.core.Request]:
        args = self.args
        relevant_states = ["new", "review"]
        if args.accepted:
            relevant_states.append("accepted")
        if args.request_id is None:
            log.debug(
                "Checking for product increment requests to be reviewed by %s on %s",
                OBS_GROUP,
                args.obs_project,
            )
            requests = osc.core.get_request_list(
                OBS_URL, project=args.obs_project, req_state=relevant_states
            )
            relevant_request = None
            for request in sorted(requests, reverse=True):
                for review in request.reviews:
                    if review.by_group == OBS_GROUP and review.state in relevant_states:
                        relevant_request = request
                        break
        else:
            log.debug("Checking specified request %i", args.request_id)
            relevant_request = osc.core.get_request(OBS_URL, str(args.request_id))
        if relevant_request is None:
            log.info(
                "Skipping approval, no relevant requests in states "
                + "/".join(relevant_states)
            )
        else:
            log.debug("Found request %s", relevant_request.id)
        return relevant_request

    def _request_openqa_job_results(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        log.debug("Checking openQA job results")
        args = self.args
        params = {"distri": args.distri, "version": args.version, "flavor": args.flavor}
        res = self.client.get_scheduled_product_stats(params)
        log.debug("Job statistics:\n%s", pformat(res))
        return res

    def _are_openqa_jobs_ready(self, res: Dict[str, Dict[str, Dict[str, Any]]]) -> bool:
        args = self.args
        actual_states = set(res.keys())
        pending_states = actual_states - final_states
        if len(actual_states) == 0:
            log.info(
                "Skipping approval, there are no relevant jobs on openQA for %s-%s-%s",
                args.distri,
                args.version,
                args.flavor,
            )
            return False
        if len(pending_states):
            log.info(
                "Skipping approval, some jobs on openQA are in pending states (%s)",
                ", ".join(sorted(pending_states)),
            )
            return False
        return True

    def _evaluate_openqa_job_results(
        self, res: Dict[str, Dict[str, Dict[str, Any]]]
    ) -> Tuple[int, List[str]]:
        ok_jobs = 0  # # count ok jobs
        reasons_to_disapprove = []  # compose list of blocking jobs
        openqa_url = self.client.url.geturl()
        for state in final_states:
            for result, info in res.get(state, {}).items():
                if result in ok_results:
                    ok_jobs += 1
                else:
                    job_list = "\n".join(
                        map(lambda id: f" - {openqa_url}/tests/{id}", info["job_ids"])
                    )
                    reasons_to_disapprove.append(
                        f"The following openQA jobs ended up with result '{result}':\n{job_list}"
                    )
        return (ok_jobs, reasons_to_disapprove)

    def _handle_approval(
        self, request: osc.core.Request, ok_jobs: int, reasons_to_disapprove: List[str]
    ) -> int:
        if len(reasons_to_disapprove) == 0:
            message = "All %i jobs on openQA have %s" % (
                ok_jobs,
                "/".join(sorted(ok_results)),
            )
            if not self.args.dry:
                osc.core.change_review_state(
                    apiurl=OBS_URL,
                    reqid=str(request.id),
                    newstate="accepted",
                    by_group=OBS_GROUP,
                    message=message,
                )
        else:
            message = "Not approving for the following reasons:\n" + "\n".join(
                reasons_to_disapprove
            )
        log.info(message)
        return 0

    def __call__(self) -> int:
        request = self._find_request_on_obs()
        if request is None:
            return 0
        res = self._request_openqa_job_results()
        if not self._are_openqa_jobs_ready(res):
            return 0
        return self._handle_approval(request, *(self._evaluate_openqa_job_results(res)))
