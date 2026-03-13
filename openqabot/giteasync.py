# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Sync Gitea pull requests to dashboard."""

from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import Any

from .loader.amqp_listener import AMQPListener
from .loader.gitea import get_open_prs, get_submissions_from_open_prs, make_submission_from_gitea_pr, make_token_header
from .loader.qem import update_submissions

log = getLogger("bot.giteasync")


class GiteaSync:
    """Synchronization of Gitea PRs to dashboard."""

    def __init__(self, args: Namespace) -> None:
        """Initialize the GiteaSync class."""
        self.dry: bool = args.dry
        self.fake_data: bool = args.fake_data
        self.gitea_token: dict[str, str] = make_token_header(args.gitea_token)
        self.pr_number: int | None = args.pr_number
        self.gitea_repo: str = args.gitea_repo
        self.allow_build_failures: bool = args.allow_build_failures
        self.consider_unrequested_prs: bool = args.consider_unrequested_prs
        self.retry = args.retry
        self.amqp = args.amqp
        self.amqp_url = args.amqp_url
        self.amqp_listener = AMQPListener(
            url=args.amqp_url,
            routing_keys=[
                "suse.src.*.pull_request.opened",
                "suse.src.*.pull_request_review_request.review_requested",
            ],
            handler=self._on_amqp_message,
        )
        self.skip_initial_sync = args.skip_initial_sync

    def __call__(self) -> int:
        """Run the synchronization process from Gitea to dashboard."""
        ret = 0
        if not self.skip_initial_sync:
            ret = self._initial_sync()
        if not self.amqp:
            return ret
        self.amqp_listener.listen()
        return 0

    def _initial_sync(self) -> int:
        open_prs: list[Any] = get_open_prs(
            self.gitea_token,
            self.gitea_repo,
            fake_data=self.fake_data,
            number=self.pr_number,
        )
        log.info(
            "Loaded %d active PRs from %s",
            len(open_prs),
            self.gitea_repo,
        )
        submissions = get_submissions_from_open_prs(
            open_prs,
            self.gitea_token,
            only_successful_builds=not self.allow_build_failures,
            only_requested_prs=not self.consider_unrequested_prs,
            dry=self.fake_data,
        )

        log.debug("Data for %d submissions: %s", len(submissions), pformat(submissions))
        if self.dry:
            log.info("Dry run: Would update QEM Dashboard data for %d submissions", len(submissions))
            return 0
        log.info("Syncing Gitea PRs to QEM Dashboard: Considering %d submissions", len(submissions))
        return update_submissions(submissions, params={"type": "git"}, retry=self.retry)

    def _on_amqp_message(self, message: dict[str, Any], _: str) -> None:
        if message["pull_request"]["base"]["repo"]["full_name"] == self.gitea_repo:
            log.info("PR #%s on %s %s", message["pull_request"]["number"], self.gitea_repo, message["action"])
            submission = make_submission_from_gitea_pr(
                message["pull_request"],
                self.gitea_token,
                only_successful_builds=not self.allow_build_failures,
                only_requested_prs=not self.consider_unrequested_prs,
                dry=self.fake_data,
            )
            log.debug("Submission: %s", submission)
            if submission and not self.dry:
                log.info("Syncing Gitea PRs #%d to QEM Dashboard", submission["number"])
                ret = update_submissions([submission], params={"type": "git"}, retry=self.retry)
                log.debug("update_submissions returned %d", ret)
