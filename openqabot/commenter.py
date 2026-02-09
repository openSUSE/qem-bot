# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Commenter class for commenting on submissions."""

from __future__ import annotations

from logging import getLogger
from pprint import pformat
from typing import TYPE_CHECKING, Any

import osc.conf
import osc.core

from openqabot import config
from openqabot.errors import NoResultsError

from .loader.qem import get_aggregate_results, get_submission_results, get_submissions
from .openqa import OpenQAInterface
from .osclib.comments import CommentAPI

if TYPE_CHECKING:
    from argparse import Namespace

    from .types.submission import Submission

log = getLogger("bot.commenter")


class Commenter:
    """Logic for commenting on submissions in OBS."""

    def __init__(self, args: Namespace) -> None:
        """Initialize the Commenter class."""
        self.dry = args.dry
        self.token = {"Authorization": f"Token {args.token}"}
        self.client = OpenQAInterface(args)
        self.submissions = get_submissions(self.token)
        osc.conf.get_config(override_apiurl=config.settings.obs_url)
        self.commentapi = CommentAPI(config.settings.obs_url)

    def __call__(self) -> int:
        """Run the commenting process."""
        log.info("Starting to comment SMELT incidents in OBS")

        for sub in self.submissions:
            if sub.type != config.settings.default_submission_type:
                log.debug("Submission %s skipped: Not a SMELT incident (type: %s)", sub, sub.type)
                continue
            try:
                s_jobs = get_submission_results(sub.id, self.token, submission_type=sub.type)
                a_jobs = get_aggregate_results(sub.id, self.token, submission_type=sub.type)
            except ValueError as e:
                log.debug(e)
                continue
            except NoResultsError as e:
                log.debug(e)
                continue

            state = "none"
            all_jobs = s_jobs + a_jobs
            if any(j["status"] == "running" for j in all_jobs):
                log.info("Postponing comment for %s: Some tests are still running", sub)
            elif any(j["status"] not in {"passed", "softfailed"} for j in all_jobs):
                log.info("Creating 'failed' comment for %s: At least one job failed", sub)
                state = "failed"
            else:
                state = "passed"

            msg = self.summarize_message(all_jobs)
            self.osc_comment(sub, msg, state)

        return 0

    def osc_comment(self, sub: Submission, msg: str, state: str) -> None:
        """Comment a submission in OBS."""
        if sub.rr is None:
            log.debug("Comment skipped for submission %s: No release request defined", sub)
            return

        if not msg:
            log.debug("Skipping empty comment")
            return

        bot_name = "openqa"
        info: dict[str, Any] = {"state": state}
        if sub.revisions:
            for key in sub.revisions:
                info[f"revision_{key.version}_{key.arch}"] = sub.revisions[key]

        msg = self.commentapi.add_marker(msg, bot_name, info)
        msg = self.commentapi.truncate(msg.strip())

        kw = {"request_id": str(sub.rr)}
        comments = self.commentapi.get_comments(**kw)
        comment, _ = self.commentapi.comment_find(comments, bot_name, info)

        # To prevent spam, assume same state/result
        # and number of lines in message is a duplicate message
        if comment is not None and comment["comment"].count("\n") == msg.count("\n"):
            log.debug("Comment skipped: Previous comment is too similar")
            return

        if comment is None:
            log.debug("No comment with this state, looking without the state filter")
            comment, _ = self.commentapi.comment_find(comments, bot_name)

        if comment is None:
            log.debug("No previous comment found to replace")
        elif not self.dry:
            self.commentapi.delete(comment["id"])
        else:
            log.info("Dry run: Would delete comment %s", comment["id"])

        if not self.dry:
            self.commentapi.add_comment(comment=msg, **kw)
        else:
            log.info("Dry run: Would write comment to request %s", sub)
            log.debug(pformat(msg))

    def summarize_message(self, jobs: list[dict[str, Any]]) -> str:
        """Summarize multiple openQA jobs into a single message."""
        groups: dict[str, dict[str, Any]] = {}
        for job in jobs:
            self._process_job(groups, job)

        msg = ""
        for group in sorted(groups.keys()):
            msg += self._format_group_message(groups[group])
        return msg.rstrip("\n")

    def _process_job(self, groups: dict[str, dict[str, Any]], job: dict[str, Any]) -> None:
        """Process a single openQA job and update its group summary."""
        if "job_group" not in job:
            # workaround for experiments of some QAM devs
            log.warning("Job %s skipped: Missing 'job_group'", job["job_id"])
            return

        gl = f"{Commenter.escape_for_markdown(job['job_group'])}@{Commenter.escape_for_markdown(job['flavor'])}"
        self._create_group_if_missing(groups, job, gl)

        job_summary = self.__summarize_one_openqa_job(job)
        if job_summary is None:
            groups[gl]["unfinished"] += 1
            return

        # None vs ''
        if not job_summary:
            groups[gl]["passed"] += 1
            return

        # if there is something to report, hold the request
        groups[gl]["failed"].append(job_summary)

    def _create_group_if_missing(self, groups: dict[str, dict[str, Any]], job: dict[str, Any], gl: str) -> None:
        """Create a new group summary entry if it doesn't exist."""
        if gl not in groups:
            groupurl = osc.core.makeurl(
                self.client.openqa.baseurl,
                ["tests", "overview"],
                {
                    "version": job["version"],
                    "groupid": job["group_id"],
                    "flavor": job["flavor"],
                    "distri": job["distri"],
                    "build": job["build"],
                },
            )
            groups[gl] = {
                "title": f"__Group [{gl}]({groupurl})__\n",
                "passed": 0,
                "unfinished": 0,
                "failed": [],
            }

    @staticmethod
    def _format_group_message(group_data: dict[str, Any]) -> str:
        """Format a single group summary into a markdown string."""
        msg = "\n\n" + group_data["title"]
        infos = []
        if group_data["passed"]:
            infos.append(f"{group_data['passed']:d} tests passed")
        if group_data["failed"]:
            infos.append(f"{len(group_data['failed']):d} tests failed")
        if group_data["unfinished"]:
            infos.append(f"{group_data['unfinished']:d} unfinished tests")
        msg += "(" + ", ".join(infos) + ")\n"
        for fail in group_data["failed"]:
            msg += fail
        return msg

    @staticmethod
    def escape_for_markdown(string: str) -> str:
        """Escape underscores for markdown."""
        return string.replace("_", r"\_")

    def __summarize_one_openqa_job(self, job: dict[str, Any]) -> str | None:
        testurl = osc.core.makeurl(self.client.openqa.baseurl, ["tests", str(job["job_id"])])
        name = job["name"]
        if job["status"] not in {"passed", "failed", "softfailed"}:
            rstring = job["status"]
            if rstring == "none":
                return None
            return f"\n- [{name}]({testurl}) is {rstring}"

        if job["status"] == "failed":  # rare case: fail without module fails
            return f"\n- [{name}]({testurl}) failed"
        return ""
