# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Approver class for approving submissions."""

from __future__ import annotations

import operator
import re
import string
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from functools import lru_cache
from http import HTTPStatus
from logging import getLogger
from typing import TYPE_CHECKING, Any
from urllib.error import HTTPError

import osc.conf
import requests
from openqa_client.exceptions import RequestError

import openqabot.config as config_module
from openqabot import config, dashboard
from openqabot.errors import JobNotFoundError, NoResultsError
from openqabot.openqa import OpenQAInterface
from openqabot.requests import approve_obs_request

from .commenter import Commenter
from .loader.gitea import approve_pr, get_open_prs, make_token_header
from .loader.qem import (
    JobAggr,
    SubReq,
    get_aggregate_settings,
    get_single_submission,
    get_submission_settings,
    get_submissions_approver,
    update_incident_reason,
)

if TYPE_CHECKING:
    from argparse import Namespace

    from openqabot.types.submission_key import SubmissionKey


class JobResult(Enum):
    """Result state of openQA jobs in an aggregate or incident setting."""

    PASSED = auto()
    FAILED = auto()
    NO_JOBS = auto()


class OlderJobResult(Enum):
    """Result of validation check on older openQA jobs."""

    OK = auto()
    NOT_OK = auto()
    KEEP_SEARCHING = auto()


log = getLogger("bot.approver")

ACCEPTABLE_FOR_TEMPLATE = r"@review:acceptable_for:(?:incident|submission)_{sub}:(.+?)(?:$|\s)"
MAINTENANCE_INCIDENT_IDENTIFIER = "Maintenance:/"


def deduplicate_jobs_by_scenario(job_results: list[dict]) -> list[dict]:
    """Keep only the most recent job (highest job_id) per scenario name.

    When a job is cloned in openQA, both the original (failed) and clone (passed)
    may exist in the dashboard. We only care about the most recent job for each
    unique scenario (identified by the 'name' field).

    Jobs without a 'name' field are not deduplicated since we cannot determine
    if they belong to different scenarios.
    """
    named_jobs = [j for j in job_results if j.get("name")]
    unnamed_jobs = [j for j in job_results if j.get("name") is None]

    if not named_jobs:
        return unnamed_jobs

    unique_names = {j["name"] for j in named_jobs if "job_id" in j}
    latest = [
        max((j for j in named_jobs if j["name"] == name), key=operator.itemgetter("job_id")) for name in unique_names
    ]

    return latest + unnamed_jobs


def handle_http_error(e: HTTPError, sub: SubReq) -> bool:
    """Handle HTTP errors from OBS API."""
    if e.code == HTTPStatus.FORBIDDEN:
        log.info("Received '%s'. Request %s likely already approved, ignoring", e.reason, sub.req)
        return True
    if e.code == HTTPStatus.NOT_FOUND:
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
    """Remove non-printable characters and newlines from comment text."""
    text = "".join(x for x in text if x in string.printable)
    text = text.replace("\r", " ").replace("\n", " ")
    return text.strip()


def mark_job_as_acceptable_for_submission(job_id: int, key: SubmissionKey) -> None:
    """Mark a job as acceptable for a submission in the dashboard.

    The dashboard identifies the incident by ``(sub, project, submission_type)``,
    so the whole ``key`` is sent with the remark. This is best-effort: failures
    are logged and approval continues, because the openQA comment that triggered
    the remark is re-read on the next run.
    """
    params: dict[str, Any] = key.to_dashboard_params(
        extra={"text": "acceptable_for", "incident_number": str(key.number)}
    )
    try:
        response = dashboard.patch(
            f"api/jobs/{job_id}/remarks",
            headers=config_module.settings.dashboard_token_dict,
            params=params,
        )
    except requests.exceptions.RequestException as e:
        log.warning(
            "Unable to mark job %i as acceptable for submission %s: %s",
            job_id,
            key,
            e,
        )
        return
    if response.status_code != HTTPStatus.OK:
        log.warning(
            "Unable to mark job %i as acceptable for submission %s: dashboard returned %s: %s",
            job_id,
            key,
            response.status_code,
            response.text,
        )


class Approver:
    """Approval logic for submissions."""

    def __init__(
        self,
        args: Namespace,
        single_submission: SubmissionKey | None = None,
        *,
        all_submissions: bool = False,
    ) -> None:
        """Initialize the Approver class.

        With ``single_submission`` set, only that incident is approved, otherwise
        every submission in QAM review. ``all_submissions`` considers the
        settings of all rounds instead of only the current one.
        """
        self.dry = args.dry
        self.gitea_token: dict[str, str] = make_token_header(args.gitea_token)
        self.single_key = single_submission
        self.all_submissions = all_submissions
        self.comment = getattr(args, "comment", False)
        self.client = OpenQAInterface()
        self.commenter = Commenter(args, submissions=[])

    def __call__(self) -> int:
        """Run the approval process.

        Returns ``0`` on success and ``1`` when a requested single submission is
        unknown or was rejected, or when any approval fails.
        """
        log.info("Starting approving submissions in OBS or Gitea…")
        if self.single_key:
            subreqs = get_single_submission(self.single_key)
            if not subreqs:
                # get_single_submission logs the dashboard's response; the
                # submission is unknown or was rejected, so there is nothing to
                # approve. Signal failure to the CLI without raising to keep
                # daemon running
                return 1
        else:
            subreqs = get_submissions_approver()

        overall_result = True
        with ThreadPoolExecutor(max_workers=config.settings.max_workers) as executor:
            approvable_flags = list(executor.map(self.approvable, subreqs))

        submissions_to_approve = [sub for sub, ok in zip(subreqs, approvable_flags, strict=True) if ok]

        log.info("Submissions to approve:")
        for sub in submissions_to_approve:
            log.info("* %s", sub.key)

        if self.dry:
            for sub in submissions_to_approve:
                log.info("Dry run: Would approve %s", sub.key)
        else:
            osc.conf.get_config(override_apiurl=config.settings.obs_url)
            with ThreadPoolExecutor(max_workers=config.settings.max_workers) as executor:
                for result in executor.map(self.approve, submissions_to_approve):
                    overall_result &= result

        log.info("Submission approval process finished")

        return 0 if overall_result else 1

    def _reject(self, sub: SubReq, reason: str) -> bool:
        reason %= sub.key
        log.info(reason)
        if self.comment and sub.submission:
            self.commenter.comment_on_submission(sub.submission)
        if not self.dry:
            update_incident_reason(sub.key, reason)
        return False

    def _evaluate_results(self, sub: SubReq, s_jobs: list[JobAggr], a_jobs: list[JobAggr]) -> bool:
        s_res = self.get_submission_result(s_jobs, "api/jobs/incident/", sub.key)
        if s_res is JobResult.FAILED:
            return self._reject(sub, "%s has at least one not-ok job in submission tests")
        if s_res is JobResult.NO_JOBS:
            return self._reject(sub, "%s has no jobs in submission tests (openQA job template mismatch?)")

        if any(s.with_aggregate for s in s_jobs):
            a_res = self.get_submission_result(a_jobs, "api/jobs/update/", sub.key)
            if a_res is JobResult.FAILED:
                return self._reject(sub, "%s has at least one not-ok job in aggregate tests")
            if a_res is JobResult.NO_JOBS:
                return self._reject(sub, "%s has no jobs in aggregate tests (openQA job template mismatch?)")

        return True

    def approvable(self, sub: SubReq) -> bool:
        """Check if a submission is ready for approval.

        A Gitea PR is approved only while its head is the commit OBS built and
        openQA tested, so a push OBS has not caught up with cannot be approved
        with the results of the previous build.
        """
        if not self.head_matches_tested_commit(sub):
            return False

        try:
            s_jobs = get_submission_settings(
                sub.key,
                all_submissions=self.all_submissions,
                scminfo=sub.scminfo,
            )
        except NoResultsError as e:
            log.info("Approval check for %s skipped: %s", sub.key, e)
            return False
        if not s_jobs:
            log.info("Approval check for %s skipped: no tests for the tested commit yet", sub.key)
            return False
        try:
            a_jobs = get_aggregate_settings(sub.key)
        except NoResultsError as e:
            if any(s.with_aggregate for s in s_jobs):
                return self._reject(sub, "Required aggregate tests missing for %s")
            log.debug("Aggregate tests optional and not found: %s", e)
            a_jobs = []

        if not self._evaluate_results(sub, s_jobs, a_jobs):
            return False

        if not self.dry:
            update_incident_reason(sub.key, None)

        # everything is green --> add submission to approve list
        return True

    def head_matches_tested_commit(self, sub: SubReq) -> bool:
        """Check that a PR head still is the commit whose tests are recorded.

        ``SubReq.scminfo`` is the revision OBS reported for the build of the PR,
        while the head is read live from Gitea so a push is noticed before the
        next sync stores it. A PR that moved to another commit than the tested
        one, or whose head cannot be read, is left unapproved until the new head
        is built and tested. Without a revision from OBS there is nothing to
        compare against and the check is skipped.
        """
        if sub.type != "git":
            return True
        prs = get_open_prs(self.gitea_token, sub.project, number=sub.sub)
        head = prs[0].commit_sha if prs else ""
        if not head or head == "unknown":
            log.warning("PR %s: cannot read the head commit from Gitea", sub.key)
            return False
        if not sub.scminfo:
            log.debug(
                "PR %s: no revision from OBS recorded, revisions cannot be told apart",
                sub.key,
            )
            return True
        if head != sub.scminfo:
            log.info(
                "PR %s: head commit %s is not the tested commit %s, approval deferred",
                sub.key,
                head,
                sub.scminfo,
            )
            return False
        return True

    @lru_cache(maxsize=512)  # ruff: ignore[cached-instance-method]
    def is_job_marked_acceptable_for_submission(self, job_id: int, sub: int) -> bool:
        """Check if a job is marked as acceptable for a submission."""
        regex = re.compile(ACCEPTABLE_FOR_TEMPLATE.format(sub=re.escape(str(sub))), re.DOTALL)
        try:
            comments = self.client.get_job_comments(job_id)
            return any(regex.search(sanitize_comment_text(comment["text"])) for comment in comments)
        except RequestError:
            return False

    @staticmethod
    @lru_cache(maxsize=512)
    def validate_job_qam(job: int) -> bool:
        """Validate if a job is present and passed in dashboard."""
        # Check that valid test result is still present in the dashboard (see
        # https://github.com/openSUSE/qem-dashboard/pull/78/files) to avoid using results related to an old release
        # request
        qam_data = dashboard.get_json(f"api/jobs/{job}", headers=config_module.settings.dashboard_token_dict)
        if not qam_data:
            return False
        if "error" in qam_data:
            log.info("Job %s not found in dashboard database, cannot validate", job)
            return False
        if qam_data["status"] != "passed":
            log.info("Job %s not 'passed' in dashboard database", job)
            return False
        return True

    @lru_cache(maxsize=16384)  # ruff: ignore[cached-instance-method]
    def job_contains_submission(self, job_id: int, sub: int) -> bool:
        """Check if a job settings contain the submission under test."""
        job_settings = self.client.get_single_job(job_id)
        if not job_settings:
            return False
        return f"{MAINTENANCE_INCIDENT_IDENTIFIER}{sub}/" in str(job_settings)

    def was_older_job_ok(
        self,
        not_ok_job_id: int,
        sub: int,
        job: dict,
        oldest_build_usable: datetime,
    ) -> OlderJobResult:
        """Check if an older job was successful and contains the submission."""
        job_build = job["build"][:-2]
        try:
            job_build_date = datetime.strptime(job_build, "%Y%m%d").astimezone(UTC)
        except (ValueError, TypeError):
            log.info("Could not parse build date '%s', cannot use for approval override.", job_build)
            return OlderJobResult.KEEP_SEARCHING

        # Check the job is not too old
        if job_build_date < oldest_build_usable:
            log.info(
                "Ignoring not-ok aggregate %s for aggregate %s skipped: Older jobs are too old",
                not_ok_job_id,
                sub,
            )
            return OlderJobResult.NOT_OK

        if job["result"] != "passed" and job["result"] != "softfailed":
            return OlderJobResult.KEEP_SEARCHING

        # Check the job contains the submission under test
        if not self.job_contains_submission(job["id"], sub):
            # Likely older jobs don't have it either. Giving up
            log.info(
                "Ignoring not-ok aggregate %s for aggregate %s skipped: "
                "Older passing jobs do not have the submission under test",
                not_ok_job_id,
                sub,
            )
            return OlderJobResult.NOT_OK

        if not self.validate_job_qam(job["id"]):
            log.info(
                "Ignoring not-ok aggregate %s using %s for aggregate %s skipped: "
                "Job not present in qem-dashboard, likely belongs to an older request",
                not_ok_job_id,
                job["id"],
                sub,
            )
            return OlderJobResult.NOT_OK

        log.info("Ignoring not-ok aggregate %s and using instead %s for aggregate %s", not_ok_job_id, job["id"], sub)
        return OlderJobResult.OK

    @lru_cache(maxsize=512)  # ruff: ignore[cached-instance-method]
    def was_ok_before(self, not_ok_job_id: int, sub: int) -> bool:
        """Check if a similar job was successful before."""
        # We need a considerable amount of older jobs, since there could be many failed manual restarts from same day
        jobs = self.client.get_older_jobs(not_ok_job_id, 20)
        data = jobs.get("data", [])
        if len(data) == 0:
            log.info("Cannot find older jobs for not-ok job %s", not_ok_job_id)
            return False

        current_job, older_jobs = data[0], data[1:]
        current_build = current_job["build"][:-2]
        try:
            current_build_date = datetime.strptime(current_build, "%Y%m%d").astimezone(UTC)
        except (ValueError, TypeError):
            log.info("Could not parse build date '%s', cannot check for older jobs.", current_build)
            return False

        # Use at most X days old build. Don't go back in time too much to reduce risk of using invalid tests
        oldest_build_usable = current_build_date - timedelta(days=config.settings.oldest_approval_job_days)

        for job in older_jobs:
            if (
                was_ok := self.was_older_job_ok(not_ok_job_id, sub, job, oldest_build_usable)
            ) is not OlderJobResult.KEEP_SEARCHING:
                return was_ok is OlderJobResult.OK
        log.info(
            "Cannot ignore aggregate failure %s for aggregate %s: No suitable older jobs found.", not_ok_job_id, sub
        )
        return False

    @staticmethod
    def is_job_passing(job_result: dict) -> bool:
        """Check if a job result status is passed."""
        return job_result["status"] == "passed"

    def mark_jobs_as_acceptable_for_submission(self, job_results: list[dict], key: SubmissionKey) -> None:
        """Mark not-ok jobs as acceptable if they have corresponding openQA comments."""
        for job_result in job_results:
            if self.is_job_passing(job_result):
                continue
            job_id = job_result["job_id"]
            try:
                if self.is_job_marked_acceptable_for_submission(job_id, key.number):
                    job_result[f"acceptable_for_{key.number}"] = True
                    mark_job_as_acceptable_for_submission(job_id, key)
            except JobNotFoundError:
                job_result["obsolete"] = True
                self.client.handle_job_not_found(job_id)

    def is_job_acceptable(self, key: SubmissionKey, api: str, job_result: dict) -> bool:
        """Determine if a job result is acceptable for approval."""
        if self.is_job_passing(job_result):
            return True
        job_id = job_result["job_id"]
        url = f"{self.client.url.geturl()}/t{job_id}"
        if job_result.get("obsolete"):
            log.info("Ignoring obsolete job %s for submission %s", url, key)
            return True
        if job_result.get(f"acceptable_for_{key.number}"):
            log.info(
                "Ignoring not-ok job %s for submission %s (manually marked as acceptable)",
                url,
                key,
            )
            return True
        if api == "api/jobs/update/" and self.was_ok_before(job_id, key.number):
            log.info(
                "Ignoring not-ok aggregate job %s for submission %s due to older ok job",
                url,
                key,
            )
            return True

        log.info("Found not-ok, not-ignored job %s for submission %s", url, key)
        return False

    @lru_cache(maxsize=128)  # ruff: ignore[cached-instance-method]
    def get_jobs(self, job_aggr: JobAggr, api: str, key: SubmissionKey) -> JobResult:
        """Retrieve jobs for a specific aggregate or incident setting.

        Note: Results are cached. If new job clones are created in openQA after
        caching, the stale cached result may be returned. Because
        ``lru_cache`` wraps this method, the key includes ``self``, the whole
        ``JobAggr`` and the submission key, not just ``job_aggr.id``. Consider
        a manual ``cache_clear()`` if fresh data is needed.
        """
        job_results = dashboard.get_json(
            api + str(job_aggr.id), headers=config_module.settings.dashboard_token_dict, params={}
        )
        if not job_results:
            # Expected for a job setting openQA never scheduled anything for
            # (e.g. flavour without matching job templates). It does not fail
            # the submission, so keep it out of the default log level; a
            # submission without any jobs at all is reported at info level by
            # get_submission_result().
            log.debug(
                "Job setting %s not found for submission %s (%s tests)",
                job_aggr.id,
                key,
                "aggregate" if job_aggr.aggregate else "submission",
            )
            return JobResult.NO_JOBS
        if not isinstance(job_results, list):
            log.warning("Unexpected job results format for job_aggr %s: %s", job_aggr.id, job_results)
            return JobResult.NO_JOBS
        original_count = len(job_results)
        job_results = deduplicate_jobs_by_scenario(job_results)
        if len(job_results) < original_count:
            log.debug(
                "Deduplicated %d jobs to %d for job_aggr %s",
                original_count,
                len(job_results),
                job_aggr.id,
            )
        self.mark_jobs_as_acceptable_for_submission(job_results, key)
        if all(self.is_job_acceptable(key, api, r) for r in job_results):
            return JobResult.PASSED
        return JobResult.FAILED

    def get_submission_result(self, jobs: list[JobAggr], api: str, key: SubmissionKey) -> JobResult:
        """Summarize results for all jobs of a submission."""
        if not jobs:
            return JobResult.NO_JOBS

        has_passed = False
        for job_aggr in jobs:
            success = self.get_jobs(job_aggr, api, key)
            if success is JobResult.FAILED:
                return JobResult.FAILED
            if success is JobResult.PASSED:
                has_passed = True

        return JobResult.PASSED if has_passed else JobResult.NO_JOBS

    def approve(self, sub: SubReq) -> bool:
        """Approve a submission in OBS or Gitea."""
        msg = f"Request accepted for '{config.settings.obs_group}' based on data in {config.settings.dashboard_url()}"
        log.info("Approving %s", sub.key)
        return self.git_approve(sub, msg) if sub.type == "git" else self.osc_approve(sub, msg)

    @staticmethod
    def osc_approve(sub: SubReq, msg: str) -> bool:
        """Approve a submission in OBS."""
        try:
            approve_obs_request(config.settings.obs_url, sub.req, msg)
        except HTTPError as e:
            return handle_http_error(e, sub)
        except Exception:
            log.exception("OBS API error: Failed to approve request %s", sub.req)
            return False
        return True

    def git_approve(self, sub: SubReq, msg: str) -> bool:
        """Approve a submission in Gitea, pinned to the commit that was tested."""
        if not sub.submission or not getattr(sub.submission, "project", None):
            log.error("Gitea API error: PR %s has no project (repo_name)", sub.sub)
            return False
        return approve_pr(self.gitea_token, sub.submission.project, sub.sub, sub.scminfo or "", msg)
