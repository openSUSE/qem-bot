# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Main OpenQABot logic."""

from argparse import Namespace
from concurrent.futures import Future, ThreadPoolExecutor, wait
from http import HTTPStatus
from logging import getLogger
from os import environ
from typing import Any

import requests

import openqabot.config as config_module
from openqabot import dashboard

from .errors import PostOpenQAError
from .loader.config import get_onearch, load_metadata
from .loader.qem import get_submissions
from .openqa import OpenQAInterface

log = getLogger("bot.openqabot")

QEM_SUMMARY_KEYS = ("incident", "project", "type", "flavor", "arch", "version", "product", "build", "repohash")
QEM_INCIDENT_KEYS = ("number", "project", "type")
MAX_RESPONSE_CHARS = 500


class OpenQABot:
    """Main OpenQABot logic."""

    def __init__(self, args: Namespace) -> None:
        """Initialize the OpenQABot class."""
        log.info("Starting bot schedule")
        self.dry = args.dry
        self.ignore_onetime = args.ignore_onetime
        self.submission_arg = args.submission if hasattr(args, "submission") else None
        self.submissions = get_submissions(self.submission_arg)
        log.info("Loaded %s submissions from QEM Dashboard", len(self.submissions))

        for sub in self.submissions:
            sub.log_skipped()

        extrasettings = get_onearch(args.singlearch)

        self.workers = load_metadata(
            args.configs,
            aggregate=args.disable_aggregates,
            submissions=args.disable_submissions,
            extrasettings=extrasettings,
        )

        self.openqa = OpenQAInterface()
        self.ci = environ.get("CI_JOB_URL")

    @staticmethod
    def _qem_summary(data: dict[str, Any]) -> dict[str, Any]:
        """Return the payload fields that identify an incident or aggregate in a log message."""
        summary = {key: data[key] for key in QEM_SUMMARY_KEYS if key in data}
        if isinstance(incidents := data.get("incidents"), list):
            summary["incidents"] = [
                {key: incident[key] for key in QEM_INCIDENT_KEYS if key in incident}
                for incident in incidents
                if isinstance(incident, dict)
            ]
        return summary

    def post_qem(self, data: dict[str, Any], api: str) -> bool:
        """Update dashboard database with job results.

        Return ``True`` when the record was written (or intentionally skipped by
        a dry run / missing openQA configuration), ``False`` when the dashboard
        rejected the request or could not be reached.
        """
        if not self.openqa:
            log.warning("Skipping dashboard update: No valid openQA configuration found for data: %s", data)
            return True

        if self.dry:
            log.info("Dry run: Would update QEM Dashboard for %s with data: %s", api, data)
            return True

        try:
            res = dashboard.put(api, headers=config_module.settings.dashboard_token_dict, json=data)
        except requests.exceptions.RequestException:
            log.exception(
                "Dashboard update failed for %s: dashboard request error. Payload: %s",
                api,
                self._qem_summary(data),
            )
            return False

        if not HTTPStatus.OK <= res.status_code < HTTPStatus.MULTIPLE_CHOICES:
            log.error(
                "Dashboard update failed for %s: Status %s, response: %r. Payload: %s",
                api,
                res.status_code,
                res.text[:MAX_RESPONSE_CHARS],
                self._qem_summary(data),
            )
            return False

        try:
            body = res.json()
        except ValueError:
            body = None
        res_id = body.get("id", "unknown") if isinstance(body, dict) else "unknown"
        log.info("Dashboard update successful for %s: Status %s, Database ID %s", api, res.status_code, res_id)
        return True

    def post_openqa(self, data: dict[str, Any]) -> bool:
        """Post a job to openQA and report whether anything was scheduled."""
        return self.openqa.post_iso(data)

    @staticmethod
    def _future_result(future: Future[bool]) -> bool:
        """Return the dashboard-update outcome of a finished job, logging dropped exceptions."""
        try:
            return future.result()
        except Exception:
            log.exception("Unexpected error while posting a job")
            return False

    def __call__(self) -> int:
        """Run the bot schedule."""
        log.info("Entering bot main loop")
        post = [p for w in self.workers for p in w(self.submissions, self.ci, ignore_onetime=self.ignore_onetime)]

        log.info("Triggering %d products in openQA", len(post))

        def poster(job: dict[str, Any]) -> bool:
            log.info("Triggering job with details from dashboard: %s", job)
            try:
                scheduled = self.post_openqa(job["openqa"])
            except PostOpenQAError:
                log.info("Skipping dashboard update: Job post failed")
                return True
            if not scheduled:
                log.info("Skipping dashboard update: openQA scheduled no job for these settings")
                return True
            return self.post_qem(job["qem"], job["api"])

        with ThreadPoolExecutor(max_workers=config_module.settings.max_workers) as executor:
            futures = [executor.submit(poster, job) for job in post]
            wait(futures)

        failed = 0
        for future in futures:
            if not self._future_result(future):
                failed += 1

        if failed:
            log.error(
                "Dashboard update failed for %s of %s jobs; these will be re-triggered on the next run",
                failed,
                len(post),
            )
            return 1

        log.info("Bot run completed")
        return 0
