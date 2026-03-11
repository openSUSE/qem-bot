# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""AMQP base module for handling RabbitMQ connections and message consumption.

This module provides the AMQPBase class which manages shared AMQP connection
and event loop logic for consuming messages from a RabbitMQ broker.
"""

import contextlib
import json
from collections.abc import Callable
from logging import getLogger
from typing import Any

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pika.spec import Basic, BasicProperties

log = getLogger("bot.amqp_base")


class AMQPListener:
    """Shared AMQP connection and event loop logic."""

    def __init__(self, url: str, routing_keys: list[str], handler: Callable[[dict, str], None]) -> None:
        """Init AMQPListener class."""
        self.url = url
        self.routing_keys = routing_keys
        self.handler = handler
        self.connection: pika.BlockingConnection | None = None
        self.channel: Any = None

    def listen(self) -> None:
        """Initialize and start the blocking consumer loop."""
        if not self.url:
            log.error("AMQP URL not provided")
            return

        try:
            self.connection = pika.BlockingConnection(pika.URLParameters(self.url))
            self.channel = self.connection.channel()
            self.channel.exchange_declare(exchange="pubsub", exchange_type="topic", passive=True, durable=True)

            result = self.channel.queue_declare("", exclusive=True)
            queue_name = result.method.queue

            for key in self.routing_keys:
                self.channel.queue_bind(exchange="pubsub", queue=queue_name, routing_key=key)

            self.channel.basic_consume(queue_name, self._on_message, auto_ack=True)

            log.info("Starting AMQP listener on %s", self.url)
            with contextlib.suppress(KeyboardInterrupt):
                self.channel.start_consuming()
        finally:
            self.stop()

    def _on_message(
        self, _ch: BlockingChannel, method: Basic.Deliver, _properties: BasicProperties, body: bytes
    ) -> None:
        message = json.loads(body)
        routing_key = method.routing_key if method.routing_key is not None else ""
        self.handler(message, routing_key)

    def stop(self) -> None:
        """Close connection if it is open."""
        if self.connection and self.connection.is_open:
            self.connection.close()
