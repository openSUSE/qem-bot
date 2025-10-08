# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from typing import Any, Dict, List, Tuple, Optional, Set, NamedTuple
import re
from logging import getLogger
from pprint import pformat

import osc.conf
import osc.core

from openqabot.openqa import openQAInterface

from .errors import PostOpenQAError
from .utils import retry10 as requests
from . import OBS_GROUP, OBS_URL, OBS_DOWNLOAD_URL

log = getLogger("bot.increment_approver")
ok_results = set(("passed", "softfailed"))
final_states = set(("done", "cancelled"))


class BuildInfo(NamedTuple):
    distri: str
    product: str
    version: str
    flavor: str
    arch: str
    build: str

    def __str__(self):
        return f"{self.product}v{self.version} build {self.build}@{self.arch} of flavor {self.flavor}"


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
            obs_requests = osc.core.get_request_list(
                OBS_URL, project=args.obs_project, req_state=relevant_states
            )
            relevant_request = None
            for request in sorted(obs_requests, reverse=True):
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
            if hasattr(relevant_request.state, "to_xml"):
                log.debug(relevant_request.to_str())
        return relevant_request

    def _request_openqa_job_results(
        self, build_info: BuildInfo
    ) -> Dict[str, Dict[str, Dict[str, Any]]]:
        log.debug("Checking openQA job results for %s", build_info)
        params = {
            "distri": build_info.distri,
            "version": build_info.version,
            "flavor": build_info.flavor,
            "arch": build_info.arch,
            "build": build_info.build,
        }
        res = self.client.get_scheduled_product_stats(params)
        log.debug("Job statistics:\n%s", pformat(res))
        return res

    def _check_openqa_jobs(
        self, res: Dict[str, Dict[str, Dict[str, Any]]], build_info: BuildInfo
    ) -> Optional[bool]:
        actual_states = set(res.keys())
        pending_states = actual_states - final_states
        if len(actual_states) == 0:
            log.info(
                "Skipping approval, there are no relevant jobs on openQA for %s",
                build_info,
            )
            return None
        if len(pending_states):
            log.info(
                "Skipping approval, some jobs on openQA for %s are in pending states (%s)",
                build_info,
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

    def _determine_build_info(self) -> Set[BuildInfo]:
        # deduce DISTRI, VERSION, FLAVOR, ARCH and BUILD from the spdx files in the repo listing similar to the sync plugin
        path = self.args.obs_project.replace(":", ":/")
        url = f"{OBS_DOWNLOAD_URL}/{path}/product/?jsontable=1"
        rows = requests.get(url).json().get("data", [])
        res = set()
        args = self.args
        for row in rows:
            m = re.search(
                "(?P<product>.*)-(?P<version>[^\\-]*?)-(?P<flavor>\\D+[^\\-]*?)-(?P<arch>[^\\-]*?)-Build(?P<build>.*?)\\.spdx.json",
                row.get("name", ""),
            )
            if m:
                product = m.group("product")
                version = m.group("version")
                flavor = m.group("flavor") + "-Increments"
                arch = m.group("arch")
                build = m.group("build")
                if product.startswith("SLE"):
                    distri = "sle"
                else:
                    continue  # skip unknown products
                if (
                    args.distri in ("any", distri)
                    and args.flavor in ("any", flavor)
                    and args.version in ("any", version)
                ):
                    res.add(BuildInfo(distri, product, version, flavor, arch, build))
        return res

    def _schedule_openqa_jobs(self, build_info: BuildInfo) -> int:
        log.info("Scheduling jobs for %s", build_info)
        if self.args.dry:
            return 0
        try:
            self.client.post_job(  # create a scheduled product with build info from spdx file
                {
                    "DISTRI": build_info.distri,
                    "VERSION": build_info.version,
                    "FLAVOR": build_info.flavor,
                    "ARCH": build_info.arch,
                    "BUILD": build_info.build,
                }
            )
            return 0
        except PostOpenQAError:
            return 1

    def __call__(self) -> int:
        error_count = 0
        request = self._find_request_on_obs()
        if request is None:
            return error_count
        for build_info in self._determine_build_info():
            res = self._request_openqa_job_results(build_info)
            if self.args.reschedule:
                error_count += self._schedule_openqa_jobs(build_info)
                continue
            openqa_jobs_ready = self._check_openqa_jobs(res, build_info)
            if openqa_jobs_ready is None and self.args.schedule:
                error_count += self._schedule_openqa_jobs(build_info)
                continue
            if not openqa_jobs_ready:
                continue
            error_count += self._handle_approval(
                request, *(self._evaluate_openqa_job_results(res))
            )
        return error_count
