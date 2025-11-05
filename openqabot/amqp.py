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
from .loader.qem import get_incident_settings_data
from .syncres import SyncRes
from .types import Data
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
            "openqa": ("suse.openqa.#", self.on_job_message),
            "gitea": (
                "suse.src.pull_request_review_request.review_requested",  # suse.src.products.pull_request_review_request.review_requested
                self.on_review_request,
            ),
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
        if self.args.dry:
            return None
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
        reviewers = message.get("pull_request", {}).get("requested_reviewers", [])
        if any(reviewer.get("username") == "qam-openqa-review" for reviewer in reviewers):
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

    def handle_inc_review_request(self, message: Dict[str, Any], args: Namespace) -> None:  # noqa: ARG002 Unused method argument
        pr_number = int(message.get("pull_request", {}).get("number"))
        if not pr_number:
            log.error("Could not extract PR number from AMQP message")
            return

        # this assumes that the incident settings are available on dashboard
        try:
            if not self.args.dry:
                settings_data: Sequence[Data] = get_incident_settings_data(self.token, pr_number)
            else:
                settings_data: Sequence[Data] = []
        except ValueError as e:
            log.error("Could not get incident settings for PR %s: %s", pr_number, e)
            return

        if not settings_data:
            log.warning("No settings data found for PR %s", pr_number)
            return

        try:
            log.info("Scheduling jobs for PR %s", pr_number)
            error_count = 0
            for s in settings_data:
                params = {
                    "DISTRI": s.distri,
                    "VERSION": s.version,
                    "FLAVOR": s.flavor,
                    "ARCH": s.arch,
                    "BUILD": s.build,
                }
                log.info(
                    "Scheduling job for %s v%s build %s@%s of flavor %s", s.distri, s.version, s.build, s.arch, s.flavor
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
                log.info("Successfully scheduled %d jobs for PR %d", len(settings_data), pr_number)

        except Exception as e:
            log.exception("Error during job scheduling for PR %s: %s", pr_number, e)
