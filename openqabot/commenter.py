# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import Any

import osc.conf
import osc.core

from openqabot.config import OBS_URL
from openqabot.errors import NoResultsError

from .loader.qem import get_aggregate_results, get_incident_results, get_incidents
from .openqa import openQAInterface
from .osclib.comments import CommentAPI
from .types.incident import Incident

log = getLogger("bot.commenter")


class Commenter:
    def __init__(self, args: Namespace) -> None:
        self.dry = args.dry
        self.token = {"Authorization": f"Token {args.token}"}
        self.client = openQAInterface(args)
        self.incidents = get_incidents(self.token)
        osc.conf.get_config(override_apiurl=OBS_URL)
        self.commentapi = CommentAPI(OBS_URL)

    def __call__(self) -> int:
        log.info("Starting to comment incidents in IBS")

        for inc in self.incidents:
            if inc.type != "smelt":
                log.debug("Incident %s skipped: Not a SMELT incident (type: %s)", inc.id, inc.type)
                continue
            try:
                i_jobs = get_incident_results(inc.id, self.token)
                u_jobs = get_aggregate_results(inc.id, self.token)
            except ValueError as e:
                log.debug(e)
                continue
            except NoResultsError as e:
                log.debug(e)
                continue

            state = "none"
            all_jobs = i_jobs + u_jobs
            if any(j["status"] == "running" for j in all_jobs):
                log.info("Postponing comment for %s: Some tests are still running", inc)
            elif any(j["status"] not in {"passed", "softfailed"} for j in all_jobs):
                log.info("Creating 'failed' comment for %s: At least one job failed", inc)
                state = "failed"
            else:
                state = "passed"

            msg = self.summarize_message(all_jobs)
            self.osc_comment(inc, msg, state)

        return 0

    def osc_comment(self, inc: Incident, msg: str, state: str) -> None:
        if inc.rr is None:
            log.debug("Comment skipped for incident %s: No release request defined", inc.id)
            return

        if not msg:
            log.debug("Skipping empty comment")
            return

        bot_name = "openqa"
        info = {"state": state}
        if inc.revisions:
            for key in inc.revisions:
                info[f"revision_{key.version}_{key.arch}"] = inc.revisions[key]

        msg = self.commentapi.add_marker(msg, bot_name, info)
        msg = self.commentapi.truncate(msg.strip())

        kw = {"request_id": str(inc.rr)}
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
            log.info("Dry run: Would write comment to request %s", inc)
            log.debug(pformat(msg))

    def summarize_message(self, jobs: list[dict[str, Any]]) -> str:  # noqa: C901
        groups = {}
        for job in jobs:
            if "job_group" not in job:
                # workaround for experiments of some QAM devs
                log.warning("Job %s skipped: Missing 'job_group'", job["job_id"])
                continue
            gl = f"{Commenter.escape_for_markdown(job['job_group'])}@{Commenter.escape_for_markdown(job['flavor'])}"
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

            job_summary = self.__summarize_one_openqa_job(job)
            if job_summary is None:
                groups[gl]["unfinished"] += 1
                continue

            # None vs ''
            if not job_summary:
                groups[gl]["passed"] += 1
                continue

            # if there is something to report, hold the request
            groups[gl]["failed"].append(job_summary)

        msg = ""
        for group in sorted(groups.keys()):
            msg += "\n\n" + groups[group]["title"]
            infos = []
            if groups[group]["passed"]:
                infos.append("{:d} tests passed".format(groups[group]["passed"]))
            if groups[group]["failed"]:
                infos.append("{:d} tests failed".format(len(groups[group]["failed"])))
            if groups[group]["unfinished"]:
                infos.append("{:d} unfinished tests".format(groups[group]["unfinished"]))
            msg += "(" + ", ".join(infos) + ")\n"
            for fail in groups[group]["failed"]:
                msg += fail
        return msg.rstrip("\n")

    @staticmethod
    def escape_for_markdown(string: str) -> str:
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
