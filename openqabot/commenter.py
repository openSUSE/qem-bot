# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Commenter class for commenting on submissions."""

from __future__ import annotations

from logging import getLogger
from pprint import pformat
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import osc.conf

from openqabot import config
from openqabot.errors import EmptyCommentError, NoResultsError

from .loader import gitea
from .loader.qem import get_aggregate_results, get_submission_results
from .openqa import OpenQAInterface
from .osclib.comments import CommentAPI

if TYPE_CHECKING:
    from argparse import Namespace
    from collections.abc import Sequence

    from .types.submission import Submission

log = getLogger("bot.commenter")


class Commenter:
    """Logic for commenting on submissions in OBS."""

    def __init__(self, args: Namespace, submissions: Sequence[Submission]) -> None:
        """Initialize the Commenter class."""
        self.dry = args.dry
        self.token = {"Authorization": f"Token {args.token}"}
        self.gitea_token = gitea.make_token_header(args.gitea_token)
        self.client = OpenQAInterface(args)
        self.submissions = submissions
        self.commentapi = CommentAPI(config.settings.obs_url)

    def __call__(self) -> int:
        """Run the commenting process."""
        log.info("Starting to comment SMELT incidents in OBS")

        for sub in self.submissions:
            self.comment_on_submission(sub)

        return 0

    def comment_on_submission(self, sub: Submission) -> None:
        """Comment on a single submission if it has openQA results."""
        if sub.type not in {config.settings.default_submission_type, "git"}:
            log.debug("Submission %s skipped: Not a SMELT incident or Gitea PR (type: %s)", sub, sub.type)
            return

        try:
            s_jobs = get_submission_results(sub.id, self.token, submission_type=sub.type)
        except (ValueError, NoResultsError) as e:
            log.debug(e)
            s_jobs = []

        try:
            a_jobs = get_aggregate_results(sub.id, self.token, submission_type=sub.type)
        except (ValueError, NoResultsError) as e:
            log.debug(e)
            a_jobs = []

        all_jobs = s_jobs + a_jobs

        if not all_jobs:
            log.debug("No jobs found for submission %s", sub)
            return

        if any(j["status"] == "running" for j in all_jobs):
            log.info("Postponing comment for %s: Some tests are still running", sub)
            return

        state = "failed" if any(j["status"] not in {"passed", "softfailed"} for j in all_jobs) else "passed"
        log.debug("Determined comment state for %s: %s", sub, state)

        msg = self.summarize_message(all_jobs)
        if not msg:
            raise EmptyCommentError(sub)

        handlers = {
            config.settings.default_submission_type: self.osc_comment,
            "git": self.gitea_comment,
        }
        handlers[sub.type](sub, msg, state)

    def osc_comment(self, sub: Submission, msg: str, state: str) -> None:
        """Comment a submission in OBS."""
        osc.conf.get_config(override_apiurl=config.settings.obs_url)
        if sub.rr is None:
            log.debug("Comment skipped for submission %s: No release request defined", sub)
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

    def gitea_comment(self, sub: Submission, msg: str, state: str) -> None:
        """Comment a submission in Gitea."""
        if not self.gitea_token:
            log.warning("Gitea token missing, skipping comment for %s", sub)
            return

        if not sub.url:
            log.warning("Submission %s has no URL, skipping Gitea comment", sub)
            return

        # Derive owner/repo from the PR URL (e.g. https://host/owner/repo/pulls/N)
        # sub.project holds the OBS project name, not the Gitea owner/repo path.
        parts = urlparse(sub.url).path.strip("/").split("/")
        repo = "/".join(parts[:2])

        bot_name = "openqa"
        info = {"state": state}
        # Add a marker so we can find our own comments later
        msg = self.commentapi.add_marker(msg, bot_name, info)

        comments = gitea.get_json_list(gitea.comments_url(repo, sub.id), self.gitea_token)
        # Convert Gitea comments to CommentAPI format
        formatted_comments = {str(c["id"]): {"id": c["id"], "comment": c["body"]} for c in comments}

        comment, _ = self.commentapi.comment_find(formatted_comments, bot_name, info)

        # To prevent spam, assume same state/result
        # and number of lines in message is a duplicate message
        if comment is not None and comment["comment"].count("\n") == msg.count("\n"):
            log.debug("Comment skipped: Previous comment is too similar")
            return

        if self.dry:
            log.info("Dry run: Would write/update comment to PR %s", sub)
            log.debug(pformat(msg))
            return

        # Unlike OBS (delete + add), Gitea supports PATCH to update in-place,
        # avoiding notification noise from a delete event followed by a new comment.
        if comment is None:
            gitea.post_json(gitea.comments_url(repo, sub.id), self.gitea_token, {"body": msg})
        else:
            gitea.patch_json(f"repos/{repo}/issues/comments/{comment['id']}", self.gitea_token, {"body": msg})

    def summarize_message(self, jobs: list[dict[str, Any]]) -> str:
        """Create markdown containing openQA badges."""
        base_url = self.client.openqa.baseurl
        builds = sorted({j["build"] for j in jobs if "build" in j})
        suffix = "" if config.settings.allow_development_groups else "&not_group_glob=*Devel*%2C*Test*"
        return "".join(
            f"[![Test Results]({base_url}/tests/overview/badge?build={b}{suffix})]"
            f"({base_url}/tests/overview?build={b}{suffix})\n"
            for b in builds
        ).strip()
