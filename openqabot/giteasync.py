# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Sync Gitea pull requests to dashboard."""

import contextlib
import json
from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import Any

import pika
import pika.channel
from pika.spec import Basic, BasicProperties

from .loader.gitea import get_open_prs, get_submissions_from_open_prs, make_submission_from_gitea_pr, make_token_header
from .loader.qem import update_submissions

log = getLogger("bot.giteasync")


class GiteaSync:
    """Synchronization of Gitea PRs to dashboard."""

    def __init__(self, args: Namespace) -> None:
        """Initialize the GiteaSync class."""
        self.dry: bool = args.dry
        self.fake_data: bool = args.fake_data
        self.dashboard_token: dict[str, str] = {"Authorization": "Token " + args.token}
        self.gitea_token: dict[str, str] = make_token_header(args.gitea_token)
        self.pr_number: int | None = args.pr_number
        self.gitea_repo: str = args.gitea_repo
        self.allow_build_failures: bool = args.allow_build_failures
        self.consider_unrequested_prs: bool = args.consider_unrequested_prs
        self.retry = args.retry
        self.amqp = args.amqp
        self.amqp_url = args.amqp_url
        self.skip_initial_sync = args.skip_initial_sync

    def __call__(self) -> int:
        """Run the synchronization process from Gitea to dashboard."""
        ret = 0
        if not self.skip_initial_sync:
            ret = self._initial_sync()
        if not self.amqp:
            return ret
        self._listen_amqp()
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
        return update_submissions(self.dashboard_token, submissions, params={"type": "git"}, retry=self.retry)

    def _listen_amqp(self) -> None:
        log.info("Listening for AMQP events for new PRs created")

        self.amqp_connection = pika.BlockingConnection(pika.URLParameters(self.amqp_url))
        self.channel = self.amqp_connection.channel()
        self.channel.exchange_declare(exchange="pubsub", exchange_type="topic", passive=True, durable=True)
        result = self.channel.queue_declare("", exclusive=True)
        queue_name = result.method.queue
        for r in [
            "suse.src.*.pull_request.opened",
            "suse.src.*.pull_request_review_request.review_requested",
        ]:
            self.channel.queue_bind(exchange="pubsub", queue=queue_name, routing_key=r)
        self.channel.basic_consume(queue_name, self._on_amqp_message, auto_ack=True)

        with contextlib.suppress(KeyboardInterrupt):
            self.channel.start_consuming()
        self.amqp_connection.close()

    def _on_amqp_message(
        self,
        _: pika.channel.Channel,
        __: Basic.Deliver,
        ___: BasicProperties,
        body: bytes,
    ) -> None:
        message = json.loads(body)
        if message["pull_request"]["base"]["repo"]["full_name"] == self.gitea_repo:
            log.info("New PR #%s on %s", message["pull_request"]["id"], self.gitea_repo)
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
                ret = update_submissions(self.dashboard_token, [submission], params={"type": "git"}, retry=self.retry)
                log.debug("update_submissions returned %d", ret)
