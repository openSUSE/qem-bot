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
    JobAggr,
    SubReq,
    get_aggregate_settings,
    get_single_submission,
    get_submission_settings,
    get_submissions_approver,
)
from .utc import UTC

log = getLogger("bot.approver")

ACCEPTABLE_FOR_TEMPLATE = r"@review:acceptable_for:(?:incident|submission)_{sub}:(.+?)(?:$|\s)"
MAINTENANCE_INCIDENT_TEMPLATE = r"(.*)Maintenance:/{sub}/(.*)"


def _ms2str(sub: SubReq) -> str:
    return f"{OBS_MAINT_PRJ}:{sub.sub}:{sub.req}" if sub.type is None else f"{sub.type}:{sub.sub}"


def _handle_http_error(e: HTTPError, sub: SubReq) -> bool:
    if e.code == 403:
        log.info("Received '%s'. Request %s likely already approved, ignoring", e.reason, sub.req)
        return True
    if e.code == 404:
        log.info(
            "OBS API error for request %s (removed or server issue): %s - %s",
            sub.req,
            e.reason,
            e.read().decode(),
        )
        return False
    log.error("OBS API error for request %s: %s - %s", sub.req, e.code, e.reason)
    return False


def sanitize_comment_text(text: str) -> str:
    text = "".join(x for x in text if x in string.printable)
    text = text.replace("\r", " ").replace("\n", " ")
    return text.strip()


class Approver:
    def __init__(
        self,
        args: Namespace,
        single_submission: int | None = None,
        submission_type: str | None = None,
    ) -> None:
        self.dry = args.dry
        self.gitea_token: dict[str, str] = make_token_header(args.gitea_token)
        if single_submission is None:
            self.single_submission = getattr(args, "submission", None) or getattr(args, "incident", None)
            self.all_submissions = args.all_submissions
            self.submission_type = None
        else:
            self.single_submission = single_submission
            self.all_submissions = False
            self.submission_type = submission_type
        self.token = {"Authorization": f"Token {args.token}"}
        self.client = openQAInterface(args)

    def __call__(self) -> int:
        log.info("Starting approving submissions in IBS or Gitea…")
        subreqs = (
            get_single_submission(self.token, self.single_submission, submission_type=self.submission_type)
            if self.single_submission
            else get_submissions_approver(self.token)
        )

        overall_result = True
        submissions_to_approve = [sub for sub in subreqs if self._approvable(sub)]

        log.info("Submissions to approve:")
        for sub in submissions_to_approve:
            log.info("* %s", _ms2str(sub))

        if not self.dry:
            osc.conf.get_config(override_apiurl=OBS_URL)
            for sub in submissions_to_approve:
                overall_result &= self.approve(sub)

        log.info("Submission approval process finished")

        return 0 if overall_result else 1

    def _approvable(self, sub: SubReq) -> bool:
        try:
            s_jobs = get_submission_settings(
                sub.sub, self.token, all_submissions=self.all_submissions, submission_type=sub.type
            )
        except NoResultsError as e:
            log.info("Approval check for %s skipped: %s", _ms2str(sub), e)
            return False
        try:
            a_jobs = get_aggregate_settings(sub.sub, self.token, submission_type=sub.type)
        except NoResultsError as e:
            if any(s.with_aggregate for s in s_jobs):
                log.info("No aggregate test results found for %s", _ms2str(sub))
                return False
            log.info(e)
            a_jobs = []

        if not self.get_submission_result(s_jobs, "api/jobs/incident/", sub.sub, submission_type=sub.type):
            log.info("%s has at least one failed job in submission tests", _ms2str(sub))
            return False

        if any(s.with_aggregate for s in s_jobs) and not self.get_submission_result(
            a_jobs, "api/jobs/update/", sub.sub, submission_type=sub.type
        ):
            log.info("%s has at least one failed job in aggregate tests", _ms2str(sub))
            return False

        # everything is green --> add submission to approve list
        return True

    def mark_job_as_acceptable_for_submission(self, job_id: int, sub: int) -> None:
        try:
            patch(f"api/jobs/{job_id}/remarks?text=acceptable_for&incident_number={sub}", headers=self.token)
        except RequestError as e:
            log.info(
                "Unable to mark job %i as acceptable for submission %s:%i: %s",
                job_id,
                self.submission_type or "smelt",
                sub,
                e,
            )

    @lru_cache(maxsize=512)
    def is_job_marked_acceptable_for_submission(self, job_id: int, sub: int) -> bool:
        regex = re.compile(ACCEPTABLE_FOR_TEMPLATE.format(sub=sub), re.DOTALL)
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
        sub: int,
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
                "Ignoring failed aggregate %s for aggregate %s skipped: Older jobs are too old",
                failed_job_id,
                sub,
            )
            return False

        if job["result"] != "passed" and job["result"] != "softfailed":
            return None

        # Check the job contains the submission under test
        job_settings = self.client.get_single_job(job["id"])
        if not regex.match(str(job_settings)):
            # Likely older jobs don't have it either. Giving up
            log.info(
                "Ignoring failed aggregate %s for aggregate %s skipped: "
                "Older passing jobs do not have the submission under test",
                failed_job_id,
                sub,
            )
            return False

        if not self.validate_job_qam(job["id"]):
            log.info(
                "Ignoring failed aggregate %s using %s for aggregate %s skipped: "
                "Job not present in qem-dashboard, likely belongs to an older request",
                failed_job_id,
                job["id"],
                sub,
            )
            return False

        log.info("Ignoring failed aggregate %s and using instead %s for aggregate %s", failed_job_id, job["id"], sub)
        return True

    @lru_cache(maxsize=512)
    def was_ok_before(self, failed_job_id: int, sub: int) -> bool:
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

        regex = re.compile(MAINTENANCE_INCIDENT_TEMPLATE.format(sub=sub))
        for job in older_jobs:
            if (was_ok := self._was_older_job_ok(failed_job_id, sub, job, oldest_build_usable, regex)) is not None:
                return was_ok
        log.info(
            "Cannot ignore aggregate failure %s for aggregate %s: No suitable older jobs found.", failed_job_id, sub
        )
        return False

    def is_job_passing(self, job_result: dict) -> bool:
        return job_result["status"] == "passed"

    def mark_jobs_as_acceptable_for_submission(self, job_results: list[dict], sub: int) -> None:
        for job_result in job_results:
            if self.is_job_passing(job_result):
                continue
            job_id = job_result["job_id"]
            if self.is_job_marked_acceptable_for_submission(job_id, sub):
                job_result[f"acceptable_for_{sub}"] = True
                self.mark_job_as_acceptable_for_submission(job_id, sub)

    def is_job_acceptable(self, sub: int, api: str, job_result: dict) -> bool:
        if self.is_job_passing(job_result):
            return True
        job_id = job_result["job_id"]
        url = f"{self.client.url.geturl()}/t{job_id}"
        if job_result.get(f"acceptable_for_{sub}"):
            log.info(
                "Ignoring failed job %s for submission %s:%s (manually marked as acceptable)",
                url,
                self.submission_type or "smelt",
                sub,
            )
            return True
        if api == "api/jobs/update/" and self.was_ok_before(job_id, sub):
            log.info(
                "Ignoring failed aggregate job %s for submission %s:%s due to older eligible openQA job being ok",
                url,
                self.submission_type or "smelt",
                sub,
            )
            return True
        log.info("Found failed, not-ignored job %s for submission %s:%s", url, self.submission_type or "smelt", sub)
        return False

    @lru_cache(maxsize=128)
    def get_jobs(self, job_aggr: JobAggr, api: str, sub: int, submission_type: str | None = None) -> bool:
        params = {}
        if submission_type:
            params["type"] = submission_type
        job_results = get_json(api + str(job_aggr.id), headers=self.token, params=params)
        if not job_results:
            msg = f"Job setting {job_aggr.id} not found for submission {submission_type or 'smelt'}:{sub}"
            raise NoResultsError(msg)
        self.mark_jobs_as_acceptable_for_submission(job_results, sub)
        return all(self.is_job_acceptable(sub, api, r) for r in job_results)

    def get_submission_result(
        self, jobs: list[JobAggr], api: str, sub: int, submission_type: str | None = None
    ) -> bool:
        if not jobs:
            return False

        res = False
        for job_aggr in jobs:
            try:
                if not self.get_jobs(job_aggr, api, sub, submission_type=submission_type):
                    return False
                res = True
            except NoResultsError as e:  # noqa: PERF203
                log.info("Approval check for submission %s:%s failed: %s", submission_type or "smelt", sub, e)
                continue

        return res

    def approve(self, sub: SubReq) -> bool:
        msg = f"Request accepted for '{OBS_GROUP}' based on data in {QEM_DASHBOARD}"
        log.info("Approving %s", _ms2str(sub))
        return self.git_approve(sub, msg) if sub.type == "git" else self.osc_approve(sub, msg)

    @staticmethod
    def osc_approve(sub: SubReq, msg: str) -> bool:
        try:
            osc.core.change_review_state(
                apiurl=OBS_URL,
                reqid=str(sub.req),
                newstate="accepted",
                by_group=OBS_GROUP,
                message=msg,
            )
        except HTTPError as e:
            return _handle_http_error(e, sub)
        except Exception:
            log.exception("OBS API error: Failed to approve request %s", sub.req)
            return False

        return True

    def git_approve(self, sub: SubReq, msg: str) -> bool:
        if not sub.url:
            log.error("Gitea API error: PR %s has no URL", sub.sub)
            return False
        try:
            path_parts = urlparse(sub.url).path.split("/")
            review_pr(
                self.gitea_token,
                "/".join(path_parts[-4:-2]),
                sub.sub,
                msg,
                sub.scm_info or "",
            )
        except Exception:
            log.exception("Gitea API error: Failed to approve PR %s", sub.sub)
            return False
        return True
