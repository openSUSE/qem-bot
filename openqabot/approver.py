# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
import string
from argparse import Namespace
from datetime import datetime, timedelta
from functools import lru_cache
from logging import getLogger
from re import Pattern
from urllib.error import HTTPError
from urllib.parse import urlparse

import osc.conf
import osc.core
from openqa_client.exceptions import RequestError

from openqabot.config import OBS_GROUP, OBS_MAINT_PRJ, OBS_URL, OLDEST_APPROVAL_JOB_DAYS, QEM_DASHBOARD
from openqabot.dashboard import get_json, patch
from openqabot.errors import NoResultsError
from openqabot.openqa import openQAInterface

from .loader.gitea import make_token_header, review_pr
from .loader.qem import (
    IncReq,
    JobAggr,
    get_aggregate_settings,
    get_incident_settings,
    get_incidents_approver,
    get_single_incident,
)
from .utc import UTC

log = getLogger("bot.approver")

ACCEPTABLE_FOR_TEMPLATE = r"@review:acceptable_for:incident_{inc}:(.+?)(?:$|\s)"
MAINTENANCE_INCIDENT_TEMPLATE = r"(.*)Maintenance:/{inc}/(.*)"


def _mi2str(inc: IncReq) -> str:
    return f"{OBS_MAINT_PRJ}:{inc.inc}:{inc.req}" if inc.type is None else f"{inc.type}:{inc.inc}"


def _handle_http_error(e: HTTPError, inc: IncReq) -> bool:
    if e.code == 403:
        log.info("Received '%s'. Request %s likely already approved, ignoring", e.reason, inc.req)
        return True
    if e.code == 404:
        log.info(
            "OBS API error for request %s (removed or server issue): %s - %s",
            inc.req,
            e.reason,
            e.read().decode(),
        )
        return False
    log.error("OBS API error for request %s: %s - %s", inc.req, e.code, e.reason)
    return False


def sanitize_comment_text(text: str) -> str:
    text = "".join(x for x in text if x in string.printable)
    text = text.replace("\r", " ").replace("\n", " ")
    return text.strip()


class Approver:
    def __init__(self, args: Namespace, single_incident: int | None = None) -> None:
        self.dry = args.dry
        self.gitea_token: dict[str, str] = make_token_header(args.gitea_token)
        if single_incident is None:
            self.single_incident = args.incident
            self.all_incidents = args.all_incidents
        else:
            self.single_incident = single_incident
            self.all_incidents = False
        self.token = {"Authorization": f"Token {args.token}"}
        self.client = openQAInterface(args)

    def __call__(self) -> int:
        log.info("Starting approving incidents in IBS or Gitea…")
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
                overall_result &= self.approve(inc)

        log.info("Incident approval process finished")

        return 0 if overall_result else 1

    def _approvable(self, inc: IncReq) -> bool:
        try:
            i_jobs = get_incident_settings(inc.inc, self.token, all_incidents=self.all_incidents)
        except NoResultsError as e:
            log.info("Approval check for %s skipped: %s", _mi2str(inc), e)
            return False
        try:
            u_jobs = get_aggregate_settings(inc.inc, self.token)
        except NoResultsError as e:
            if any(i.with_aggregate for i in i_jobs):
                log.info("No aggregate test results found for %s", _mi2str(inc))
                return False
            log.info(e)
            u_jobs = []

        if not self.get_incident_result(i_jobs, "api/jobs/incident/", inc.inc):
            log.info("%s has at least one failed job in incident tests", _mi2str(inc))
            return False

        if any(i.with_aggregate for i in i_jobs) and not self.get_incident_result(u_jobs, "api/jobs/update/", inc.inc):
            log.info("%s has at least one failed job in aggregate tests", _mi2str(inc))
            return False

        # everything is green --> add incident to approve list
        return True

    def mark_job_as_acceptable_for_incident(self, job_id: int, inc: int) -> None:
        try:
            patch(f"api/jobs/{job_id}/remarks?text=acceptable_for&incident_number={inc}", headers=self.token)
        except RequestError as e:
            log.info("Unable to mark job %i as acceptable for incident %i: %s", job_id, inc, e)

    @lru_cache(maxsize=512)
    def is_job_marked_acceptable_for_incident(self, job_id: int, inc: int) -> bool:
        regex = re.compile(ACCEPTABLE_FOR_TEMPLATE.format(inc=inc), re.DOTALL)
        try:
            comments = self.client.get_job_comments(job_id)
            return any(regex.search(sanitize_comment_text(comment["text"])) for comment in comments)
        except RequestError:
            return False

    @lru_cache(maxsize=512)
    def validate_job_qam(self, job: int) -> bool:
        # Check that valid test result is still present in the dashboard (see
        # https://github.com/openSUSE/qem-dashboard/pull/78/files) to avoid using results related to an old release
        # request
        qam_data = get_json(f"api/jobs/{job}", headers=self.token)
        if not qam_data:
            return False
        if "error" in qam_data:
            log.info("Job %s not found in dashboard database, cannot validate", job)
            return False
        if qam_data["status"] != "passed":
            log.info("Job %s not 'passed' in dashboard database", job)
            return False
        return True

    def _was_older_job_ok(
        self,
        failed_job_id: int,
        inc: int,
        job: dict,
        oldest_build_usable: datetime,
        regex: Pattern[str],
    ) -> bool | None:
        job_build = job["build"][:-2]
        try:
            job_build_date = datetime.strptime(job_build, "%Y%m%d").astimezone(UTC)
        except (ValueError, TypeError):
            log.info("Could not parse build date '%s', cannot use for approval override.", job_build)
            return None

        # Check the job is not too old
        if job_build_date < oldest_build_usable:
            log.info(
                "Ignoring failed aggregate %s for update %s skipped: Older jobs are too old",
                failed_job_id,
                inc,
            )
            return False

        if job["result"] != "passed" and job["result"] != "softfailed":
            return None

        # Check the job contains the update under test
        job_settings = self.client.get_single_job(job["id"])
        if not regex.match(str(job_settings)):
            # Likely older jobs don't have it either. Giving up
            log.info(
                "Ignoring failed aggregate %s for update %s skipped: "
                "Older passing jobs do not have the update under test",
                failed_job_id,
                inc,
            )
            return False

        if not self.validate_job_qam(job["id"]):
            log.info(
                "Ignoring failed aggregate %s using %s for update %s skipped: "
                "Job not present in qem-dashboard, likely belongs to an older request",
                failed_job_id,
                job["id"],
                inc,
            )
            return False

        log.info("Ignoring failed aggregate %s and using instead %s for update %s", failed_job_id, job["id"], inc)
        return True

    @lru_cache(maxsize=512)
    def was_ok_before(self, failed_job_id: int, inc: int) -> bool:
        # We need a considerable amount of older jobs, since there could be many failed manual restarts from same day
        jobs = self.client.get_older_jobs(failed_job_id, 20)
        data = jobs.get("data", [])
        if len(data) == 0:
            log.info("Cannot find older jobs for failed job %s", failed_job_id)
            return False

        current_job, older_jobs = data[0], data[1:]
        current_build = current_job["build"][:-2]
        try:
            current_build_date = datetime.strptime(current_build, "%Y%m%d").astimezone(UTC)
        except (ValueError, TypeError):
            log.info("Could not parse build date '%s', cannot check for older jobs.", current_build)
            return False

        # Use at most X days old build. Don't go back in time too much to reduce risk of using invalid tests
        oldest_build_usable = current_build_date - timedelta(days=OLDEST_APPROVAL_JOB_DAYS)

        regex = re.compile(MAINTENANCE_INCIDENT_TEMPLATE.format(inc=inc))
        for job in older_jobs:
            if (was_ok := self._was_older_job_ok(failed_job_id, inc, job, oldest_build_usable, regex)) is not None:
                return was_ok
        log.info("Cannot ignore aggregate failure %s for update %s: No suitable older jobs found.", failed_job_id, inc)
        return False

    def is_job_passing(self, job_result: dict) -> bool:
        return job_result["status"] == "passed"

    def mark_jobs_as_acceptable_for_incident(self, job_results: list[dict], inc: int) -> None:
        for job_result in job_results:
            if self.is_job_passing(job_result):
                continue
            job_id = job_result["job_id"]
            if self.is_job_marked_acceptable_for_incident(job_id, inc):
                job_result[f"acceptable_for_{inc}"] = True
                self.mark_job_as_acceptable_for_incident(job_id, inc)

    def is_job_acceptable(self, inc: int, api: str, job_result: dict) -> bool:
        if self.is_job_passing(job_result):
            return True
        job_id = job_result["job_id"]
        url = f"{self.client.url.geturl()}/t{job_id}"
        if job_result.get(f"acceptable_for_{inc}"):
            log.info("Ignoring failed job %s for incident %s (manually marked as acceptable)", url, inc)
            return True
        if api == "api/jobs/update/" and self.was_ok_before(job_id, inc):
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
        job_results = get_json(api + str(job_aggr.id), headers=self.token)
        if not job_results:
            msg = f"Job setting {job_aggr.id} not found for incident {inc}"
            raise NoResultsError(msg)
        self.mark_jobs_as_acceptable_for_incident(job_results, inc)
        return all(self.is_job_acceptable(inc, api, r) for r in job_results)

    def get_incident_result(self, jobs: list[JobAggr], api: str, inc: int) -> bool:
        res = False

        for job_aggr in jobs:
            try:
                res = self.get_jobs(job_aggr, api, inc)
            except NoResultsError as e:
                log.info("Approval check for incident %s failed: %s", inc, e)
                continue
            if not res:
                return False

        return res

    def approve(self, inc: IncReq) -> bool:
        msg = f"Request accepted for '{OBS_GROUP}' based on data in {QEM_DASHBOARD}"
        log.info("Approving %s", _mi2str(inc))
        return self.git_approve(inc, msg) if inc.type == "git" else self.osc_approve(inc, msg)

    @staticmethod
    def osc_approve(inc: IncReq, msg: str) -> bool:
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
        except Exception:
            log.exception("OBS API error: Failed to approve request %s", inc.req)
            return False

        return True

    def git_approve(self, inc: IncReq, msg: str) -> bool:
        if not inc.url:
            log.error("Gitea API error: PR %s has no URL", inc.inc)
            return False
        try:
            path_parts = urlparse(inc.url).path.split("/")
            review_pr(
                self.gitea_token,
                "/".join(path_parts[-4:-2]),
                inc.inc,
                msg,
                inc.scm_info or "",
            )
        except Exception:
            log.exception("Gitea API error: Failed to approve PR %s", inc.inc)
            return False
        return True
