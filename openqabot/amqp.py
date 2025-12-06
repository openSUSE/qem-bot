# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import contextlib
import json
import re
from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import TYPE_CHECKING, Any

import pika
import pika.channel
import pika.spec

from .approver import Approver
from .loader.qem import get_incident_settings_data
from .syncres import SyncRes
from .types import Data
from .utils import compare_incident_data

if TYPE_CHECKING:
    from collections.abc import Sequence


log = getLogger("bot.amqp")
build_inc_regex = re.compile(r":(\d+):.*")
build_agg_regex = re.compile(r"\d{8}-\d+")


class AMQP(SyncRes):
    def __init__(self, args: Namespace) -> None:
        super().__init__(args)
        self.args = args
        self.dry: bool = args.dry
        self.token: dict[str, str] = {"Authorization": f"Token {args.token}"}
        self.connection = None
        self.channel = None
        if not args.url:
            return
        # Based on https://rabbit.suse.de/files/amqp_get_suse.py
        self.connection = pika.BlockingConnection(pika.URLParameters(args.url))
        self.channel = self.connection.channel()
        self.channel.exchange_declare(exchange="pubsub", exchange_type="topic", passive=True, durable=True)
        result = self.channel.queue_declare("", exclusive=True)
        queue_name = result.method.queue
        self.channel.queue_bind(exchange="pubsub", queue=queue_name, routing_key="suse.openqa.#")
        self.channel.basic_consume(queue_name, self.on_message, auto_ack=True)

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

    def on_message(
        self,
        _: pika.channel.Channel,
        method: pika.spec.Basic.Deliver,
        __: pika.spec.BasicProperties,
        body: bytes,
    ) -> None:
        message = json.loads(body)
        if method.routing_key == "suse.openqa.job.done" and "BUILD" in message:
            match = build_inc_regex.match(message["BUILD"])
            if match:
                inc_nr = match.group(1)
                log.debug("Received AMQP message: %s", pformat(message))
                log.info("Job for incident %s done", inc_nr)
                return self.handle_incident(inc_nr, message)
            match = build_agg_regex.match(message["BUILD"])
            if match:
                build_nr = match.group(0)
                log.debug("Received AMQP message: %s", pformat(message))
                log.info("Aggregate build %s done", build_nr)
        return None

    def _fetch_openqa_results(self, inc: Data, message: dict[str, Any]) -> None:
        AMQP.operation = "incident"
        for job in self.client.get_jobs(inc):
            if self.filter_jobs(job) and (r := self._normalize_data(inc, job)) and r["job_id"] == message["id"]:
                self.post_result(r)

    def handle_incident(self, inc_nr: int, message: dict[str, Any]) -> None:
        # Load Data about current incident from dashboard database
        try:
            settings: Sequence[Data] = get_incident_settings_data(self.token, inc_nr)
        except ValueError:
            return

        for inc in settings:
            # Filter out not matching incident Data
            if not compare_incident_data(inc, message):
                continue
            self._fetch_openqa_results(inc, message)

        # Try to approve incident
        approve = Approver(self.args, inc_nr)
        approve()
