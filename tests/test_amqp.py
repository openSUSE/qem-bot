# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# ruff: noqa: S106 "Possible hardcoded password assigned to argument"
from __future__ import annotations

import json
import logging
from argparse import Namespace
from typing import Any, NamedTuple, cast
from urllib.parse import urlparse

import pytest
from pytest_mock import MockerFixture

import responses
from openqabot.amqp import AMQP
from openqabot.config import DEFAULT_SUBMISSION_TYPE
from openqabot.types.types import Data


class FakeMethod(NamedTuple):
    routing_key: str


fake_job_done = FakeMethod("suse.openqa.job.done")


@pytest.fixture
def args() -> Namespace:
    return Namespace(
        dry=True,
        token="ToKeN",
        openqa_instance=urlparse("http://instance.qa"),
        url=None,
        gitea_token=None,
    )


@pytest.fixture
def amqp(args: Namespace) -> AMQP:
    return AMQP(args)


def test_init_no_url(amqp: AMQP) -> None:
    assert amqp.connection is None
    amqp.stop()


def test_call(mocker: MockerFixture, args: Namespace) -> None:
    mocker.patch("openqabot.amqp.pika")
    args.url = "amqp://test.url"
    amqp_with_url = AMQP(args)
    amqp_with_url()
    amqp_with_url.channel.start_consuming.assert_called_once()
    amqp_with_url.connection.close.assert_called_once()


def test_call_no_channel(caplog: pytest.LogCaptureFixture, args: Namespace) -> None:
    caplog.set_level(logging.ERROR)
    amqp_no_url = AMQP(args)
    assert amqp_no_url() == 1
    assert "AMQP listener not started: No channel available" in caplog.text


@pytest.mark.parametrize(
    ("build", "expected_type", "expected_id"),
    [
        (f":{DEFAULT_SUBMISSION_TYPE}:33222:emacs", DEFAULT_SUBMISSION_TYPE, 33222),
        (":33222:emacs", DEFAULT_SUBMISSION_TYPE, 33222),
        (":gitea:123:foo", "gitea", 123),
    ],
)
def test_on_message_parsing(
    amqp: AMQP, mocker: MockerFixture, build: str, expected_type: str, expected_id: int
) -> None:
    mock_handle = mocker.patch.object(amqp, "handle_submission")
    message = {"BUILD": build}
    body = json.dumps(message).encode()

    amqp.on_message(cast("Any", ""), cast("Any", fake_job_done), cast("Any", ""), body)

    mock_handle.assert_called_once_with(expected_id, expected_type, message)


@responses.activate
def test_handling_aggregate(caplog: pytest.LogCaptureFixture, amqp: AMQP) -> None:
    caplog.set_level(logging.DEBUG)
    amqp.on_message(
        cast("Any", ""), cast("Any", fake_job_done), cast("Any", ""), json.dumps({"BUILD": "12345678-9"}).encode()
    )

    assert "Aggregate 12345678-9: openQA build finished" in caplog.messages  # currently noop


def test_on_message_bad_routing_key(caplog: pytest.LogCaptureFixture, amqp: AMQP) -> None:
    caplog.set_level(logging.DEBUG)
    fake_job_fail = FakeMethod("suse.openqa.job.fail")
    amqp.on_message(
        cast("Any", ""),
        cast("Any", fake_job_fail),
        cast("Any", ""),
        json.dumps({"BUILD": "12345678-9"}).encode(),
    )
    assert not caplog.text


def test_on_message_no_build(caplog: pytest.LogCaptureFixture, amqp: AMQP) -> None:
    caplog.set_level(logging.DEBUG)
    amqp.on_message(
        cast("Any", ""), cast("Any", fake_job_done), cast("Any", ""), json.dumps({"NOBUILD": "12345678-9"}).encode()
    )
    assert not caplog.text


def test_on_message_bad_build(caplog: pytest.LogCaptureFixture, amqp: AMQP) -> None:
    caplog.set_level(logging.DEBUG)
    amqp.on_message(
        cast("Any", ""), cast("Any", fake_job_done), cast("Any", ""), json.dumps({"BUILD": "badbuild"}).encode()
    )
    assert not caplog.text


@responses.activate
def test_handle_submission_value_error(caplog: pytest.LogCaptureFixture, mocker: MockerFixture, amqp: AMQP) -> None:
    caplog.set_level(logging.DEBUG)
    mocker.patch("openqabot.amqp.get_submission_settings_data", side_effect=ValueError)
    amqp.handle_submission(33222, DEFAULT_SUBMISSION_TYPE, {})
    assert not caplog.text


def test_handle_submission_updates_dashboard_entry(mocker: MockerFixture, amqp: AMQP) -> None:
    mocker.patch("openqabot.approver.get_single_submission")
    mocker.patch("openqabot.amqp.get_submission_settings_data", return_value=[0])
    mocker.patch("openqabot.amqp.compare_submission_data", return_value=True)
    mocker.patch("openqabot.openqa.openQAInterface.get_jobs", return_value=[0])
    fetch_openqa_results_mock = mocker.patch("openqabot.amqp.AMQP._fetch_openqa_results", return_value=True)

    amqp.handle_submission(42, DEFAULT_SUBMISSION_TYPE, {})
    fetch_openqa_results_mock.assert_called()


def test_handle_submission_exception(mocker: MockerFixture, amqp: AMQP) -> None:
    mocker.patch("openqabot.amqp.get_submission_settings_data", side_effect=Exception("error"))
    with pytest.raises(Exception, match="error"):
        amqp.handle_submission(42, DEFAULT_SUBMISSION_TYPE, {})


def test_handle_submission_not_matching_data(mocker: MockerFixture, amqp: AMQP) -> None:
    mocker.patch("openqabot.approver.get_single_submission")
    mocker.patch("openqabot.amqp.get_submission_settings_data", return_value=[0])
    mocker.patch("openqabot.amqp.compare_submission_data", return_value=False)
    fetch_openqa_results_mock = mocker.patch("openqabot.amqp.AMQP._fetch_openqa_results")

    amqp.handle_submission(42, DEFAULT_SUBMISSION_TYPE, {})
    fetch_openqa_results_mock.assert_not_called()


def test_fetch_openqa_results_calls_post_result(mocker: MockerFixture, amqp: AMQP) -> None:
    job = {"id": 42}
    r = {"job_id": 42}
    message = job

    mocker.patch("openqabot.amqp.AMQP.filter_jobs", return_value=True)
    normalize_data_mock = mocker.patch("openqabot.amqp.AMQP._normalize_data", return_value=r)
    post_result_mock = mocker.patch("openqabot.amqp.AMQP.post_result")
    get_jobs_mock = mocker.patch("openqabot.openqa.openQAInterface.get_jobs", return_value=[job])

    amqp._fetch_openqa_results(cast("Data", {}), message)  # noqa: SLF001
    post_result_mock.assert_called_once_with(r)
    normalize_data_mock.assert_called_once_with({}, job)
    get_jobs_mock.assert_called_once_with({})


def test_fetch_openqa_results_unfiltered(mocker: MockerFixture, amqp: AMQP) -> None:
    job = {"id": 42}
    message = job

    mocker.patch("openqabot.amqp.AMQP.filter_jobs", return_value=False)
    post_result_mock = mocker.patch("openqabot.amqp.AMQP.post_result")
    mocker.patch("openqabot.openqa.openQAInterface.get_jobs", return_value=[job])

    amqp._fetch_openqa_results(cast("Data", {}), message)  # noqa: SLF001
    post_result_mock.assert_not_called()


def test_fetch_openqa_results_key_error(mocker: MockerFixture, amqp: AMQP) -> None:
    job = {"id": 42}
    message = job

    mocker.patch("openqabot.amqp.AMQP.filter_jobs", return_value=True)
    mocker.patch("openqabot.amqp.AMQP._normalize_data", return_value=None)
    post_result_mock = mocker.patch("openqabot.amqp.AMQP.post_result")
    mocker.patch("openqabot.openqa.openQAInterface.get_jobs", return_value=[job])

    amqp._fetch_openqa_results(cast("Data", {}), message)  # noqa: SLF001
    post_result_mock.assert_not_called()


def test_fetch_openqa_results_no_id(mocker: MockerFixture, amqp: AMQP) -> None:
    job = {"id": 42}
    r = {"job_id": 42}
    message = {"id": 43}

    mocker.patch("openqabot.amqp.AMQP.filter_jobs", return_value=True)
    mocker.patch("openqabot.amqp.AMQP._normalize_data", return_value=r)
    post_result_mock = mocker.patch("openqabot.amqp.AMQP.post_result")
    mocker.patch("openqabot.openqa.openQAInterface.get_jobs", return_value=[job])

    amqp._fetch_openqa_results(cast("Data", {}), message)  # noqa: SLF001
    post_result_mock.assert_not_called()
