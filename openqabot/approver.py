# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from functools import lru_cache
from logging import getLogger
from typing import List, Pattern, Optional
from urllib.error import HTTPError
from datetime import timedelta, datetime
import re

import osc.conf
import osc.core

from openqa_client.exceptions import RequestError
from openqabot.errors import NoResultsError
from openqabot.openqa import openQAInterface
from openqabot.dashboard import get_json

from . import OBS_GROUP, OBS_MAINT_PRJ, OBS_URL, QEM_DASHBOARD, OLDEST_APPROVAL_JOB_DAYS
from .loader.qem import (
    IncReq,
    JobAggr,
    get_aggregate_settings,
    get_incident_settings,
    get_incidents_approver,
    get_single_incident,
)

log = getLogger("bot.approver")


def _mi2str(inc: IncReq) -> str:
    return "%s:%s:%s" % (OBS_MAINT_PRJ, str(inc.inc), str(inc.req))


def _handle_http_error(e: HTTPError, inc: IncReq) -> bool:
    if e.code == 403:
        log.info(
            "Received '%s'. Request %s likely already approved, ignoring",
            e.reason,
            inc.req,
        )
        return True
    if e.code == 404:
        log.info(
            "Received '%s'. Request %s removed or problem on OBS side: %s",
            e.reason,
            inc.req,
            e.read().decode(),
        )
        return False
    log.error(
        "Received error %s, reason: '%s' for Request %s - problem on OBS side",
        e.code,
        e.reason,
        inc.req,
    )
    return False


class Approver:
    def __init__(self, args: Namespace, single_incident=None) -> None:
        self.dry = args.dry
        if single_incident is None:
            self.single_incident = args.incident
            self.all_incidents = args.all_incidents
        else:
            self.single_incident = single_incident
            self.all_incidents = False
        self.token = {"Authorization": "Token {}".format(args.token)}
        self.client = openQAInterface(args)

    def __call__(self) -> int:
        log.info("Start approving incidents in IBS")
        increqs = (
            get_single_incident(self.token, self.single_incident)
            if self.single_incident
            else get_incidents_approver(self.token)
        )

        overall_result = True
        incidents_to_approve = [inc for inc in increqs if self._approvable(inc)]

        log.info("Incidents to approve:")
        for inc in incidents_to_approve:
            log.info("* %s", _mi2str(inc))

        if not self.dry:
            osc.conf.get_config(override_apiurl=OBS_URL)
            for inc in incidents_to_approve:
                overall_result &= self.osc_approve(inc)

        log.info("End of bot run")

        return 0 if overall_result else 1

    def _approvable(self, inc: IncReq) -> bool:
        try:
            i_jobs = get_incident_settings(inc.inc, self.token, self.all_incidents)
        except NoResultsError as e:
            log.info(e)
            return False
        try:
            u_jobs = get_aggregate_settings(inc.inc, self.token)
        except NoResultsError as e:
            log.info(e)

            if any(i.withAggregate for i in i_jobs):
                log.info("Aggregate missing for %s", _mi2str(inc))
                return False

            u_jobs = []

        if not self.get_incident_result(i_jobs, "api/jobs/incident/", inc.inc):
            log.info("%s has at least one failed job in incident tests", _mi2str(inc))
            return False

        if any(i.withAggregate for i in i_jobs):
            if not self.get_incident_result(u_jobs, "api/jobs/update/", inc.inc):
                log.info(
                    "%s has at least one failed job in aggregate tests", _mi2str(inc)
                )
                return False

        # everything is green --> add incident to approve list
        return True

    @lru_cache(maxsize=512)
    def is_job_marked_acceptable_for_incident(self, job_id: int, inc: int) -> bool:
        regex = re.compile(r"\@review\:acceptable_for\:incident_%s\:(.+)" % inc)
        try:
            for comment in self.client.get_job_comments(job_id):
                if regex.match(comment["text"]):
                    return True
        except RequestError:
            pass
        return False

    @lru_cache(maxsize=512)
    def validate_job_qam(self, job: int) -> bool:
        # Check that valid test result is still present in the dashboard (see https://github.com/openSUSE/qem-dashboard/pull/78/files) to avoid using results related to an old release request
        qam_data = get_json("api/jobs/" + str(job), headers=self.token)
        if not qam_data:
            return False
        if "error" in qam_data:
            log.info(
                "Cannot find job %s in the dashboard database to make sure it is valid",
                job,
            )
            return False
        if qam_data["status"] != "passed":
            log.info(
                'Job %s is not recorded as "passed" in the qam-dashboard database',
                job,
            )
            return False
        return True

    def _was_older_job_ok(
        self,
        failed_job_id: int,
        inc: int,
        job: dict,
        oldest_build_usable: datetime,
        regex: Pattern[str],
    ) -> Optional[bool]:
        job_build = job["build"][:-2]
        try:
            job_build_date = datetime.strptime(job_build, "%Y%m%d")
        except (ValueError, TypeError):
            log.info("Could not parse build date %s", job_build)
            return None

        # Check the job is not too old
        if job_build_date < oldest_build_usable:
            log.info(
                "Cannot ignore aggregate failure %s for update %s because: Older jobs are too old to be considered"
                % (failed_job_id, inc)
            )
            return False

        if job["result"] != "passed" and job["result"] != "softfailed":
            return None

        # Check the job contains the update under test
        job_settings = self.client.get_single_job(job["id"])
        if not regex.match(str(job_settings)):
            # Likely older jobs don't have it either. Giving up
            log.info(
                "Cannot ignore aggregate failure %s for update %s because: Older passing jobs do not have update under test"
                % (failed_job_id, inc)
            )
            return False

        if not self.validate_job_qam(job["id"]):
            log.info(
                "Cannot ignore failed aggregate %s using %s for update %s because is not present in qem-dashboard. It's likely about an older release request"
                % (failed_job_id, job["id"], inc)
            )
            return False

        log.info(
            "Ignoring failed aggregate %s and using instead %s for update %s"
            % (failed_job_id, job["id"], inc)
        )
        return True

    @lru_cache(maxsize=512)
    def was_ok_before(self, failed_job_id: int, inc: int) -> bool:
        # We need a considerable amount of older jobs, since there could be many failed manual restarts from same day
        jobs = self.client.get_older_jobs(failed_job_id, 20)
        if jobs == []:
            log.info("Cannot find older jobs for %s", failed_job_id)
            return False

        current_job, older_jobs = jobs["data"][0], jobs["data"][1:]
        current_build = current_job["build"][:-2]
        try:
            current_build_date = datetime.strptime(current_build, "%Y%m%d")
        except (ValueError, TypeError):
            log.info("Could not parse build date %s", current_build)
            return False

        # Use at most X days old build. Don't go back in time too much to reduce risk of using invalid tests
        oldest_build_usable = current_build_date - timedelta(
            days=OLDEST_APPROVAL_JOB_DAYS
        )

        regex = re.compile(r"(.*)Maintenance:/%s/(.*)" % inc)
        for job in older_jobs:
            was_ok = self._was_older_job_ok(
                failed_job_id, inc, job, oldest_build_usable, regex
            )
            if was_ok is not None:
                return was_ok
        log.info(
            "Cannot ignore aggregate failure %s for update %s because: Older usable jobs did not succeed. Run out of jobs to evaluate."
            % (failed_job_id, inc)
        )
        return False

    def job_acceptable(self, inc: int, api: str, res) -> bool:
        """
        Check each job if it is acceptable for different reasons.

        Keep jobs marked as acceptable for one incident by openQA comments.

        Keep jobs marked as acceptable if are aggregate and were ok in the previous days.
        """
        if res["status"] == "passed":
            return True
        url = "{}/t{}".format(self.client.url.geturl(), res["job_id"])
        if self.is_job_marked_acceptable_for_incident(res["job_id"], inc):
            log.info(
                "Ignoring failed job %s for incident %s due to openQA comment", url, inc
            )
            return True
        if api == "api/jobs/update/" and self.was_ok_before(res["job_id"], inc):
            log.info(
                "Ignoring failed aggregate job %s for incident %s due to older eligible openQA job being ok",
                url,
                inc,
            )
            return True
        log.info("Found failed, not-ignored job %s for incident %s", url, inc)
        return False

    @lru_cache(maxsize=128)
    def get_jobs(self, job_aggr: JobAggr, api: str, inc: int) -> bool:
        results = get_json(api + str(job_aggr.id), headers=self.token)
        if not results:
            raise NoResultsError(
                "Job setting %s not found for incident %s"
                % (str(job_aggr.id), str(inc))
            )
        return all(self.job_acceptable(inc, api, r) for r in results)

    def get_incident_result(self, jobs: List[JobAggr], api: str, inc: int) -> bool:
        res = False

        for job_aggr in jobs:
            try:
                res = self.get_jobs(job_aggr, api, inc)
            except NoResultsError as e:
                log.info(e)
                continue
            if not res:
                return False

        return res

    @staticmethod
    def osc_approve(inc: IncReq) -> bool:
        msg = (
            "Request accepted for '" + OBS_GROUP + "' based on data in " + QEM_DASHBOARD
        )
        log.info("Accepting review for %s:%s:%s", OBS_MAINT_PRJ, inc.inc, inc.req)

        try:
            osc.core.change_review_state(
                apiurl=OBS_URL,
                reqid=str(inc.req),
                newstate="accepted",
                by_group=OBS_GROUP,
                message=msg,
            )
        except HTTPError as e:
            return _handle_http_error(e, inc)
        except Exception as e:  # pylint: disable=broad-except
            log.exception(e)
            return False

        return True
