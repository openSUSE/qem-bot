# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Commenter class for commenting on submissions."""

from __future__ import annotations

from logging import getLogger
from pprint import pformat
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urlparse

import osc.conf

from openqabot import config
from openqabot.errors import EmptyCommentError, NoResultsError

from .loader import gitea
from .loader.qem import get_aggregate_results, get_submission_results
from .openqa import OpenQAInterface
from .osclib.comments import CommentAPI, add_marker, truncate
from .types.increment import BuildIdentifier
from .utils import extract_contact_from_description, normalize_results

if TYPE_CHECKING:
    from argparse import Namespace
    from collections.abc import Callable, Sequence

    from .types.pullrequest import CommentableProtocol
    from .types.submission import Submission

log = getLogger("bot.commenter")


class Commenter:
    """Logic for commenting on submissions in OBS."""

    def __init__(self, args: Namespace, submissions: Sequence[Submission]) -> None:
        """Initialize the Commenter class."""
        self.dry = args.dry
        self.gitea_token = gitea.make_token_header(args.gitea_token)
        self.client = OpenQAInterface()
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

        def get_jobs(func: Callable[[int, str | None], list[dict[str, Any]]]) -> list[dict[str, Any]]:
            try:
                return func(sub.id, sub.type)
            except (ValueError, NoResultsError) as e:
                log.debug(e)
                return []

        all_jobs = get_jobs(get_submission_results) + get_jobs(get_aggregate_results)

        if res := self.generate_comment(sub, all_jobs):
            handlers = {config.settings.default_submission_type: self.osc_comment, "git": self.gitea_comment}
            handlers[sub.type](sub, *res)

    def calculate_state(self, jobs: list[dict[str, Any]]) -> str:  # noqa: PLR6301
        """Calculate overall state of jobs."""
        return "passed" if all(j["status"] in {"passed", "softfailed"} for j in jobs) else "failed"

    def generate_comment(self, sub: CommentableProtocol, jobs: list[dict[str, Any]]) -> tuple[str, str] | None:
        """Generate comment message and state for a set of jobs."""
        if not jobs:
            log.debug("No jobs found for submission %s", sub)
            return None

        def get_stat(j: dict[str, Any]) -> str:
            if "status" in j:
                return j["status"]
            return normalize_results(j.get("result", "none")) if j.get("state") == "done" else "running"

        jobs = [{**j, "status": get_stat(j)} for j in jobs]

        if any(j["status"] == "running" for j in jobs):
            log.info("Postponing comment for %s: Some tests are still running", sub)
            return None

        state = self.calculate_state(jobs)
        log.debug("Determined comment state for %s: %s", sub, state)

        builds = {BuildIdentifier.from_job(j) for j in jobs if "build" in j}
        msg = self.summarize_message(builds, jobs)
        if not msg:
            raise EmptyCommentError(sub)

        return msg, state

    def osc_comment_on_request(
        self, request_id: str, msg: str, state: str, revisions: dict[str, Any] | None = None
    ) -> None:
        """Comment on an OBS request."""
        osc.conf.get_config(override_apiurl=config.settings.obs_url)
        bot_name = "openqa"
        info: dict[str, Any] = {"state": state}
        if revisions:
            info.update(revisions)

        msg = add_marker(msg, bot_name, info)
        msg = truncate(msg.strip())

        comments = self.commentapi.get_comments(request_id=request_id)
        comment, _ = self.commentapi.comment_find(comments, bot_name, info)

        # To prevent spam, assume same state/result
        # and number of lines in message is a duplicate message
        if comment and comment["comment"].count("\n") == msg.count("\n"):
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
            self.commentapi.add_comment(comment=msg, request_id=request_id)
        else:
            log.info("Dry run: Would write comment to request %s", request_id)
            log.debug(pformat(msg))

    def osc_comment(self, sub: Submission, msg: str, state: str) -> None:
        """Comment a submission in OBS."""
        if sub.rr is None:
            log.debug("Comment skipped for submission %s: No release request defined", sub)
            return

        revisions = {f"revision_{k.version}_{k.arch}": v for k, v in sub.revisions.items()} if sub.revisions else None
        self.osc_comment_on_request(str(sub.rr), msg, state, revisions=revisions)

    def gitea_comment(self, sub: CommentableProtocol, msg: str, state: str) -> None:
        """Comment a submission in Gitea."""
        if not self.gitea_token:
            log.warning("Gitea token missing, skipping comment for %s", sub)
            return

        if not sub.url:
            log.warning("Submission %s has no URL, skipping Gitea comment", sub)
            return

        # Derive owner/repo from the PR URL (e.g. https://host/owner/repo/pulls/N)
        # sub.project holds the OBS project name, not the Gitea owner/repo path.
        repo = "/".join(urlparse(sub.url).path.strip("/").split("/")[:2])

        # Add a marker so we can find our own comments later
        msg = add_marker(msg, "openqa", {"state": state})

        comments = gitea.iter_gitea_items(gitea.comments_url(repo, sub.id), self.gitea_token)
        formatted = {str(c["id"]): {"id": c["id"], "comment": c["body"]} for c in comments}
        comment, info = self.commentapi.comment_find(formatted, "openqa")

        # To prevent spam, assume same state/result
        # and number of lines in message is a duplicate message
        if comment and info and info.get("state") == state and comment["comment"].count("\n") == msg.count("\n"):
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

    def summarize_message(self, builds: set[BuildIdentifier], jobs: list[dict[str, Any]]) -> str:
        """Create markdown containing openQA badges."""
        badge_msg = self._generate_badge_section(builds)

        if not config.settings.enable_detailed_comments:
            return badge_msg

        job_groups = self.get_job_groups_with_failures(jobs)
        if not job_groups:
            return badge_msg

        return badge_msg + "\n\n" + self._generate_detail_section(job_groups, sorted(builds))

    def _generate_badge_section(self, builds: set[BuildIdentifier]) -> str:
        """Generate markdown for openQA badges."""
        base_url = self.client.openqa.baseurl
        badge_msg = ""
        for b in sorted(builds):
            params = b.get_base_badge_params()
            label = f"Build {b.build}"
            params["label"] = label
            query = urlencode(params, safe="*")
            badge_url = f"{base_url}/tests/overview/badge?{query}"
            link_url = f"{base_url}/tests/overview?{query}"
            badge_msg += f"[![{label} Results]({badge_url})]({link_url})\n"
        return badge_msg.strip()

    def _generate_detail_section(self, job_groups: list[dict[str, Any]], sorted_builds: list[BuildIdentifier]) -> str:
        """Generate markdown for detailed failure information."""
        max_entries = config.settings.max_detailed_comment_entries
        display_groups = job_groups[:max_entries]
        excluded_count = len(job_groups) - max_entries

        fallback = config.settings.fallback_contact
        base_url = self.client.openqa.baseurl

        table_rows = [
            f"| [![{g['name']} Test Results]({g['badge_url']})]({g['overview_url']}) | "
            f"{g['contact'] or f'No contact provided: {fallback}'} |"
            for g in display_groups
        ]

        detail_msg = "\n\n| *Job Group with blocking failures* | *Group Owner's contact information*\n| --- | --- |\n"
        detail_msg += "\n".join(table_rows)

        if excluded_count > 0:
            params = sorted_builds[0].get_base_badge_params()
            query = urlencode(params, safe="*")
            overview_link = f"{base_url}/tests/overview?{query}"
            detail_msg += (
                f"\n\n*... and {excluded_count} more job groups. See [Test Results]({overview_link}) for details.*"
            )

        detail_msg += f"\n\nFor generic tool issues, contact {config.settings.generic_tool_issues_contact}."
        return detail_msg.strip()

    def get_job_groups_with_failures(self, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Get job groups with blocking failures and their contact info."""
        base_url = self.client.openqa.baseurl

        groups: dict[int, dict[str, Any]] = {}
        for job in jobs:
            status = job.get("status", "")
            if status in {"passed", "softfailed"}:
                continue
            group_id = job.get("group_id")
            if not group_id:
                continue
            if group_id not in groups:
                group_info = self.client.get_job_group_info(group_id)
                groups[group_id] = {
                    "id": group_id,
                    "name": group_info.get("name", "Unknown") if group_info else "Unknown",
                    "description": group_info.get("description") if group_info else None,
                    "contact": None,
                    "build": job.get("build", ""),
                    "distri": job.get("distri", ""),
                    "version": job.get("version", ""),
                    "status": status,
                }
                if group_info:
                    groups[group_id]["contact"] = extract_contact_from_description(group_info.get("description"))

        return [
            {
                "id": g["id"],
                "name": (name := str(g["name"])),
                "contact": g["contact"],
                "build": g["build"],
                "status": g["status"],
                "overview_url": _generate_overview_url(base_url, g, name),
                "badge_url": _generate_overview_url(base_url, g, name, badge=True, label=name),
            }
            for g in groups.values()
        ]


def _generate_overview_url(
    base_url: str, group: dict[str, Any], group_name: str, *, badge: bool = False, label: str | None = None
) -> str:
    """Generate overview or badge URL for a specific job group."""
    params = BuildIdentifier(
        group.get("build", ""), group.get("distri", ""), group.get("version", "")
    ).get_base_badge_params()
    params["group"] = group_name
    if label:
        params["label"] = label

    query = urlencode(params, safe="*")
    path = "/tests/overview/badge" if badge else "/tests/overview"
    return f"{base_url}{path}?{query}"
