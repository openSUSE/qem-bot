# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# ruff: noqa: S106 "Possible hardcoded password assigned to argument"
import json
import logging
from typing import NamedTuple
from unittest.mock import patch
from urllib.parse import urlparse

from _pytest.logging import LogCaptureFixture

import responses
from openqabot import QEM_DASHBOARD
from openqabot.amqp import AMQP


class Namespace(NamedTuple):
    dry: bool
    token: str
    openqa_instance: str
    url: str
    gitea_token: str


args = Namespace(
    dry=True,
    token="ToKeN",
    openqa_instance=urlparse("http://instance.qa"),
    url=None,
    gitea_token=None,
)
amqp = AMQP(args)


class FakeMethod(NamedTuple):
    routing_key: str


fake_job_done = FakeMethod("suse.openqa.job.done")


def test_init_no_url() -> None:
    assert amqp.connection is None


def test_call() -> None:
    with patch("openqabot.amqp.pika"):
        args_with_url = Namespace(
            dry=True,
            token="ToKeN",
            openqa_instance=urlparse("http://instance.qa"),
            url="amqp://test.url",
            gitea_token=None,
        )
        amqp_with_url = AMQP(args_with_url)
        amqp_with_url()
        amqp_with_url.channel.start_consuming.assert_called_once()
        amqp_with_url.connection.close.assert_called_once()


@responses.activate
def test_handling_incident(caplog: LogCaptureFixture) -> None:
    # define response for get_incident_settings_data
    data = [
        {
            "id": 110,
            "flavor": "FakeFlavor",
            "arch": "arch",
            "settings": {"DISTRI": "linux", "BUILD": "33222"},
            "version": "13.3",
            "withAggregate": False,
        },
    ]
    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/incident_settings/33222",
        json=data,
    )

    # define response for get_aggregate_settings
    data = [
        {
            "id": 110,
            "flavor": "FakeFlavor",
            "arch": "arch",
            "settings": {"DISTRI": "linux", "BUILD": "33222"},
            "version": "13.3",
            "build": "33222",
        },
    ]
    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/update_settings/33222",
        json=data,
    )

    # define response for get_jobs
    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/jobs/incident/110",
        json=[{"incident_settings": 1000, "job_id": 110, "status": "passed"}],
    )

    # define incident
    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/incidents/33222",
        json={"number": 33222, "rr_number": 42},
    )

    caplog.set_level(logging.DEBUG)
    amqp.on_message("", fake_job_done, "", json.dumps({"BUILD": ":33222:emacs"}))

    messages = [x[-1] for x in caplog.record_tuples]
    assert "Job for incident 33222 done" in messages
    assert "Incidents to approve:" in messages
    assert "* SUSE:Maintenance:33222:42" in messages


@responses.activate
def test_handling_aggregate(caplog: LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    amqp.on_message("", fake_job_done, "", json.dumps({"BUILD": "12345678-9"}))

    messages = [x[-1] for x in caplog.record_tuples]
    assert "Aggregate build 12345678-9 done" in messages  # currently noop


def test_on_message_bad_routing_key(caplog: LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    fake_job_fail = FakeMethod("suse.openqa.job.fail")
    amqp.on_message(
        "",
        fake_job_fail,
        "",
        json.dumps({"BUILD": "12345678-9"}),
    )
    assert not caplog.text


def test_on_message_no_build(caplog: LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    amqp.on_message("", fake_job_done, "", json.dumps({"NOBUILD": "12345678-9"}))
    assert not caplog.text
