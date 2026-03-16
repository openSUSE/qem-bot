# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""AMQP listener for openQA events."""

import re
from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import TYPE_CHECKING, Any

from .approver import Approver
from .config import settings
from .loader.amqp_listener import AMQPListener
from .loader.qem import get_submission_settings_data
from .syncres import SyncRes
from .types.types import Data
from .utils import compare_submission_data

if TYPE_CHECKING:
    from collections.abc import Sequence


log = getLogger("bot.amqp")
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
            sub_nr = match.group("id")
            log.debug("Processing AMQP message: %s", pformat(message))
            log.info("Submission %s:%s: openQA job finished", sub_type, sub_nr)
            return self.handle_submission(int(sub_nr), sub_type, message)
        if match := build_agg_regex.match(message["BUILD"]):
            build_nr = match.group(0)
            log.debug("Processing AMQP message: %s", pformat(message))
            log.info("Aggregate %s: openQA build finished", build_nr)
        return None

    def fetch_openqa_results(self, sub: Data, message: dict[str, Any]) -> None:
        """Fetch results from openQA for a specific submission."""
        AMQP.operation = "submission"
        for job in self.client.get_jobs(sub):
            if self.filter_jobs(job) and (r := self.normalize_data_safe(sub, job)) and r["job_id"] == message["id"]:
                self.post_result(r)

    def handle_submission(self, sub_nr: int, sub_type: str, message: dict[str, Any]) -> None:
        """Handle results for a specific submission and trigger approval."""
        # Load Data about current submission from dashboard database
        try:
            settings: Sequence[Data] = get_submission_settings_data(sub_nr, submission_type=sub_type)
        except ValueError:
            return

        for sub in settings:
            # Filter out not matching submission Data
            if not compare_submission_data(sub, message):
                continue
            self.fetch_openqa_results(sub, message)

        # Try to approve submission
        approve = Approver(self.args, single_submission=sub_nr, submission_type=sub_type)
        approve()
