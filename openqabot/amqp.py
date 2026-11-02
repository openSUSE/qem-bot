# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""AMQP listener for openQA events."""

import re
from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import TYPE_CHECKING, Any

import requests
from openqa_client.exceptions import OpenQAClientError

from .approver import Approver
from .config import settings
from .errors import JobNotFoundError
from .loader.amqp_listener import AMQPListener
from .loader.qem import get_submission_settings_data
from .syncres import SyncRes
from .types.submission_key import SubmissionKey
from .types.types import Data
from .utils import compare_submission_data

if TYPE_CHECKING:
    from collections.abc import Sequence


log = getLogger("bot.amqp")
# Submission BUILD settings are generated as ``:{type}:{id}:{package}`` (see
# Submissions.get_base_settings).  The id is numeric; the project that the
# submission belongs to is carried separately (QEM_DASHBOARD_PROJECT openQA variable), so it is
# not part of the regex.
build_sub_regex = re.compile(r":(?:(?P<type>[^:]+):)?(?P<id>\d+)(?::.*)?")
build_agg_regex = re.compile(r"\d{8}-\d+")


class AMQP(SyncRes):
    """AMQP listener and message handler."""

    def __init__(self, args: Namespace) -> None:
        """Initialize the AMQP class."""
        super().__init__(args)
        self.args = args
        self.amqp_listener = AMQPListener(url=args.url, routing_keys=["suse.openqa.#"], handler=self.on_message)

    def __call__(self) -> int:
        """Start the AMQP listener."""
        self.amqp_listener.listen()
        return 0

    def on_message(self, message: dict[str, Any], routing_key: str) -> None:
        """Handle incoming AMQP message."""
        if routing_key != "suse.openqa.job.done" or "BUILD" not in message:
            return None
        if match := build_sub_regex.match(message["BUILD"]):
            sub_type = match.group("type") or settings.default_submission_type
            sub_nr = int(match.group("id"))
            log.debug("Processing AMQP message: %s", pformat(message))
            log.info("Submission %s:%s: openQA job finished", sub_type, sub_nr)
            return self.handle_submission(sub_nr, sub_type, message)
        if match := build_agg_regex.match(message["BUILD"]):
            build_nr = match.group(0)
            log.debug("Processing AMQP message: %s", pformat(message))
            log.info("Aggregate %s: openQA build finished", build_nr)
        return None

    def _project_from_job(self, message: dict[str, Any]) -> str | None:
        """Read the QEM dashboard project of the job that just finished.

        The AMQP job.done payload does not carry custom job settings, so the
        project is read back from openQA where ``QEM_DASHBOARD_PROJECT`` was set
        by ``Submissions.get_base_settings``.

        Returns ``None`` when the message has no job id, the job does not exist
        on openQA, openQA cannot be queried, or the job carries no
        ``QEM_DASHBOARD_PROJECT``. Each case is logged distinctly so that an
        openQA failure is not mistaken for a job without a project.
        """
        job_id = message.get("id")
        if job_id is None:
            log.warning("Job.done message without a job id, cannot determine its project")
            return None
        try:
            job = self.client.get_single_job(job_id, raise_errors=True)
        except JobNotFoundError:
            log.warning("Job %s not found on openQA, cannot determine its project", job_id)
            return None
        except (OpenQAClientError, requests.exceptions.RequestException):
            log.exception("openQA API error when fetching job %s, cannot determine its project", job_id)
            return None
        if not job:
            log.warning("openQA returned no data for job %s, cannot determine its project", job_id)
            return None
        project = (job.get("settings") or {}).get("QEM_DASHBOARD_PROJECT")
        if not project:
            log.warning("Job %s has no QEM_DASHBOARD_PROJECT, cannot determine its project", job_id)
        return project

    def fetch_openqa_results(self, sub: Data, message: dict[str, Any]) -> None:
        """Fetch results from openQA for a specific submission."""
        AMQP.operation = "submission"
        for job in self.client.get_jobs(sub):
            if self.filter_jobs(job) and (r := self.normalize_data_safe(sub, job)) and r["job_id"] == message["id"]:
                self.post_result(r)

    def handle_submission(self, sub_nr: int, sub_type: str, message: dict[str, Any]) -> None:
        """Handle results for a specific submission and trigger approval.

        The dashboard project is read back from the finished job. When it cannot
        be determined the submission is skipped with a warning, so a job
        scheduled before ``QEM_DASHBOARD_PROJECT`` existed cannot kill the
        daemon.
        """
        project = self._project_from_job(message)
        if project is None:
            # _project_from_job already logged the concrete reason (missing job
            # id, job not found, openQA error, or unset QEM_DASHBOARD_PROJECT).
            # The dashboard requires a project for api/incident_settings and
            # api/incidents, so skip this message instead of letting a single
            # project-less job kill the daemon.
            return
        # Load Data about current submission from dashboard database
        key = SubmissionKey(sub_type, project, sub_nr)
        try:
            settings: Sequence[Data] = get_submission_settings_data(key)
        except ValueError:
            return

        for sub in settings:
            # Filter out not matching submission Data
            if not compare_submission_data(sub, message):
                continue
            self.fetch_openqa_results(sub, message)

        # Try to approve submission
        approve = Approver(self.args, single_submission=key)
        approve()
