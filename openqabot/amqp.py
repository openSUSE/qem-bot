# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import contextlib
import json
import re
from argparse import Namespace
from logging import getLogger
from typing import Any, Dict, Sequence

import pika
import pika.channel
import pika.spec

from .approver import Approver
from .errors import PostOpenQAError
from .loader.gitea import make_incident_from_pr, make_token_header
from .loader.qem import get_incident_settings_data
from .syncres import SyncRes
from .types import Data
from .types.incident import Incident
from .utils import compare_incident_data

log = getLogger("bot.amqp")
build_inc_regex = re.compile(r":(\d+):.*")
build_agg_regex = re.compile(r"\d{8}-\d+")


class AMQP(SyncRes):
    def __init__(self, args: Namespace) -> None:
        super().__init__(args)
        self.args = args
        self.dry: bool = args.dry
        self.token: Dict[str, str] = {"Authorization": f"Token {args.token}"}
        if not args.url:
            return
        routing_keys = {
            "openqa": ("*.openqa.#", self.on_job_message),
            "gitea": ("*.pull_request_review_request.#", self.on_review_request),
        }
        # Based on https://rabbit.suse.de/files/amqp_get_suse.py
        self.connection = pika.BlockingConnection(pika.URLParameters(args.url))
        self.channel = self.connection.channel()
        self.channel.exchange_declare(exchange="pubsub", exchange_type="topic", passive=True, durable=True)
        for queue in args.queue:
            if queue in routing_keys:
                routing_key, callback = routing_keys[queue]
                self.setup_consumer(routing_key, callback, queue)

    def setup_consumer(self, routing_key: str, callback: Any, queue_name: str) -> None:
        result = self.channel.queue_declare(queue="", exclusive=True)
        queue_name = result.method.queue
        log.debug("Starting %s queue", queue_name)
        self.channel.queue_bind(exchange="pubsub", queue=queue_name, routing_key=routing_key)
        self.channel.basic_consume(queue=queue_name, on_message_callback=callback, auto_ack=True)

    def __call__(self) -> int:
        log.info("AMQP listening started")
        with contextlib.suppress(KeyboardInterrupt):
            self.channel.start_consuming()
        self.stop()
        return 0

    def stop(self) -> None:
        if self.connection:
            log.info("Closing AMQP connection")
            self.connection.close()

    def on_job_message(
        self,
        channel: pika.channel.Channel,  # noqa: ARG002 Unused method argument
        method: pika.spec.Basic.Deliver,
        properties: pika.spec.BasicProperties,  # noqa: ARG002 Unused method argument
        body: bytes,
    ) -> None:
        log.info("%s - Received openQA job message", method.routing_key)
        log.debug(" %s - %s", method.routing_key, body.decode())
        message = json.loads(body)

        if method.routing_key == "suse.openqa.job.done" and "BUILD" in message:
            match = build_inc_regex.match(message["BUILD"])
            if match:
                inc_nr = match.group(1)
                log.info("Job for incident %s done", inc_nr)
                return self.handle_incident(inc_nr, message)
            match = build_agg_regex.match(message["BUILD"])
            if match:
                build_nr = match.group(0)
                log.info("Aggregate build %s done", build_nr)
                return self.handle_aggregate(build_nr, message)
        return None

    def on_review_request(
        self,
        channel: pika.channel.Channel,  # noqa: ARG002 Unused method argument
        method: pika.spec.Basic.Deliver,
        properties: pika.spec.BasicProperties,  # noqa: ARG002 Unused method argument
        body: bytes,
    ) -> None:
        log.info("%s - Received Gitea review request message", method.routing_key)
        log.debug(" %s - %s", method.routing_key, body.decode())
        message = json.loads(body)

        def _has_build_succeeded() -> bool:
            review_tag = message.get("review", "")
            if not review_tag or review_tag == "null":
                return False
            is_type_approved = review_tag.get("type") == "pull_request_review_approved"
            is_build_success = review_tag.get("content") == "Build successful"
            return is_type_approved and is_build_success

        def _has_reviewer_qam_openqa_review() -> bool:
            reviewers = message.get("pull_request", {}).get("requested_reviewers", [])
            return any(reviewer.get("username") == "qam-openqa-review" for reviewer in reviewers)

        if _has_build_succeeded() and _has_reviewer_qam_openqa_review():
            return self.handle_inc_review_request(message, self.args)
        return None

    def handle_incident(self, inc_nr: int, message: Dict[str, Any]) -> None:
        # Load Data about current incident from dashboard database
        try:
            if not self.args.dry:
                settings: Sequence[Data] = get_incident_settings_data(self.token, inc_nr)
            else:
                settings: Sequence[Data] = []
        except ValueError:
            return

        for inc in settings:
            # Filter out not matching incident Data
            if not compare_incident_data(inc, message):
                continue
            # Fetch results from openQA about this incident (AMQP data does not contain enough information)
            for v in self.client.get_jobs(inc):
                if not self.filter_jobs(v):
                    continue
                try:
                    AMQP.operation = "incident"
                    r = self.normalize_data(inc, v)
                except KeyError:
                    continue
                # Post update about matching openQA job into dashboard database
                if r["job_id"] == message["id"]:
                    self.post_result(r)

        # Try to approve incident
        approve = Approver(self.args, inc_nr)
        approve()

    def handle_aggregate(self, unused_build: str, unused_message: Dict[str, Any]) -> None:  # noqa: ARG002 Unused method argument
        return

    def handle_inc_review_request(self, message: Dict[str, Any], args: Namespace) -> None:
        try:
            pr_number = int(message.get("pull_request", {}).get("number"))
        except (ValueError, TypeError):
            log.error("Could not extract PR number from AMQP message")
            return

        pr_data = message.get("pull_request", {})
        if not pr_data:
            log.error("No pull_request data in AMQP message")
            return

        gitea_token = make_token_header(getattr(args, "gitea_token", None))
        # Fetch incident data from Gitea/OBS using make_incident_from_pr
        log.info("Fetching incident data for PR %s from Gitea/OBS", pr_number)
        incident_data = make_incident_from_pr(
            pr=pr_data,
            token=gitea_token,
            only_successful_builds=True,
            only_requested_prs=False,
            dry=self.args.dry,
        )

        if incident_data is None:
            log.warning("No incident data for PR %s", pr_number)
            return

        incident = Incident.create(incident_data)
        log.info(incident)
        # Schedule jobs for each repo/arch combination now
        error_count = 0
        for channel in incident.channels:
            log.info("Scheduling jobs for PR %s with %d channel(s)", pr_number, len(incident.channels))
            # For Gitea PRs, BUILD format is ":PR_NUMBER:package"
            build = f":{pr_number}:{incident.packages[0]}" if incident.packages else f":{pr_number}:unknown"

            params = {
                "DISTRI": "sle",
                "VERSION": channel.product_version if channel.product_version else channel.version,
                "FLAVOR": "Server-DVD-Updates",
                "ARCH": channel.arch,
                "BUILD": build,
                "INCIDENT_ID": pr_number,
            }

            log.info(
                "Review Request %s with medium type variables is going to be scheduled in openQA: %s %s %s %s",
                pr_number,
                params["DISTRI"],
                params["VERSION"],
                params["BUILD"],
                params["ARCH"],
            )

            if self.dry:
                log.info("Dry run - would schedule: %s", params)
                continue

            try:
                self.client.post_job(params)
            except PostOpenQAError as e:
                log.error("Failed to schedule job with params %s: %s", params, e)
                error_count += 1

        if error_count > 0:
            log.error("Failed to schedule %d jobs for PR %d", error_count, pr_number)
        else:
            log.info("Successfully scheduled %d jobs for PR %d", len(incident.channels), pr_number)
