# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test AMQPListener."""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from openqabot.loader.amqp_listener import AMQPListener


def test_listener_full_workflow(mocker: MagicMock) -> None:
    mock_conn = mocker.patch("pika.BlockingConnection")
    mock_channel = MagicMock()
    mock_conn.return_value.channel.return_value = mock_channel

    mock_channel.queue_declare.return_value.method.queue = "tmp-queue"

    received_data = []

    def fake_handler(msg: Any, key: str) -> None:
        received_data.append((msg, key))

    listener = AMQPListener(
        url="amqp://guest:guest@localhost:5672/%2f", routing_keys=["test.key"], handler=fake_handler
    )

    mock_channel.start_consuming.side_effect = KeyboardInterrupt()

    listener.listen()

    # 4. Assert: Verify the pika setup calls (Lines 30-44)
    mock_channel.exchange_declare.assert_called_with(
        exchange="pubsub", exchange_type="topic", passive=True, durable=True
    )
    mock_channel.queue_bind.assert_called_with(exchange="pubsub", queue="tmp-queue", routing_key="test.key")
    fake_body = json.dumps({"foo": "bar"}).encode("utf-8")
    fake_method = MagicMock(routing_key="test.key")
    listener._on_message(None, fake_method, None, fake_body)  # type: ignore[invalid-argument-type]  # noqa: SLF001

    assert received_data[0] == ({"foo": "bar"}, "test.key")


def test_listen_no_url(caplog: pytest.LogCaptureFixture) -> None:
    listener = AMQPListener(url="", routing_keys=[], handler=lambda _, __: None)
    listener.listen()
    assert "AMQP URL not provided" in caplog.text


def test_stop_connection_none() -> None:
    """Covers the branch where self.connection is None."""
    listener = AMQPListener("url", [], lambda _, __: None)
    listener.connection = None
    listener.stop()


def test_stop_connection_closed(mocker: MagicMock) -> None:
    """Covers the branch where self.connection exists but is_open is False."""
    listener = AMQPListener("url", [], lambda _, __: None)
    mock_conn = mocker.MagicMock()
    mock_conn.is_open = False
    listener.connection = mock_conn
    listener.stop()
    assert not mock_conn.close.called
