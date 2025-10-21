# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import Dict, Sequence

import json
import re
import pika

from .syncres import SyncRes
from .types import Data
from .loader.qem import get_incident_settings_data
from .utils import compare_incident_data
from .approver import Approver


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
        try:
            self.channel.start_consuming()
        except KeyboardInterrupt:
            pass
        self.stop()
        return 0

    def stop(self):
        if self.connection:
            log.info("Closing AMQP connection")
            self.connection.close()

    def on_message(self, unused_channel, method, unused_properties, body) -> None:
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
                return self.handle_aggregate(build_nr, message)
        return None

    def handle_incident(self, inc_nr: int, message) -> None:
        # Load Data about current incident from dashboard database
        try:
            settings: Sequence[Data] = get_incident_settings_data(self.token, inc_nr)
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

    def handle_aggregate(self, unused_build: str, unused_message) -> None:
        return
