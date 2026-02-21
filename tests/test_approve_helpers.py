# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test approve helpers."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, NoReturn

import pytest
from openqa_client.exceptions import RequestError

from openqabot.approver import Approver
from openqabot.utc import UTC

from .helpers import args

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_is_job_marked_acceptable_for_submission_request_error(mocker: MockerFixture) -> None:
    mocker.patch(
        "openqabot.openqa.OpenQAInterface.get_job_comments",
        side_effect=RequestError("Get out", url="http://foo.bar", status_code=404, text="Not Found"),
    )
    approver_instance = Approver(args)
    assert not approver_instance.is_job_marked_acceptable_for_submission(1, 1)


def test_mark_job_as_acceptable_for_submission_request_error(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    def f_patch(*_args: Any, **_kwds: Any) -> NoReturn:
        msg = "Patch failed"
        raise RequestError(msg, url="http://foo.bar", status_code=500, text="Internal Server Error")

    caplog.set_level(logging.INFO)
    approver_instance = Approver(args)
    mocker.patch("openqabot.approver.patch", side_effect=f_patch)
    approver_instance.mark_job_as_acceptable_for_submission(1, 1)
    assert "Unable to mark job 1 as acceptable for submission smelt:1" in caplog.text


@pytest.mark.parametrize(
    "json_data", [pytest.param(None, id="no_qam_data"), pytest.param({"status": "failed"}, id="status_not_passed")]
)
def test_validate_job_qam_no_qam_data(json_data: dict, mocker: MockerFixture) -> None:
    approver_instance = Approver(args)
    mocker.patch("openqabot.approver.get_json", return_value=json_data)
    assert not approver_instance.validate_job_qam(1)


@pytest.mark.parametrize(
    ("job", "log_message"),
    [
        ({"build": "invalid-date", "result": "passed", "id": 123}, "Could not parse build date"),
        ({"build": "20200101-1", "result": "passed", "id": 123}, "Older jobs are too old"),
    ],
)
def testwas_older_job_ok_returns_none(job: dict, log_message: str, caplog: pytest.LogCaptureFixture) -> None:
    approver_instance = Approver(args)
    oldest_build_usable = datetime.now(UTC) - timedelta(days=1)

    caplog.set_level(logging.INFO)
    assert not approver_instance.was_older_job_ok(1, 1, job, oldest_build_usable)
    assert any(log_message in m for m in caplog.messages)


@pytest.mark.parametrize(
    ("older_jobs_data", "log_message"),
    [
        pytest.param(
            {"build": "20240101XY", "result": "failed", "id": 123},
            "No suitable older jobs found",
            id="no_suitable_older_jobs",
        ),
        pytest.param(
            {"build": "invalid-date"},
            "Could not parse build date",
            id="invalid_date",
        ),
    ],
)
def test_was_ok_before_no_suitable_older_jobs(
    older_jobs_data: dict, log_message: str, caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    approver_instance = Approver(args)
    caplog.set_level(logging.INFO)
    mocker.patch("openqabot.openqa.OpenQAInterface.get_older_jobs", return_value={"data": [older_jobs_data]})
    mocker.patch("openqabot.approver.Approver.was_older_job_ok")
    assert not approver_instance.was_ok_before(1, 1)
    assert any(log_message in m for m in caplog.messages)


def test_get_submission_result_empty_jobs() -> None:
    approver_instance = Approver(args)
    assert approver_instance.get_submission_result([], "api/", 1) is False


def test_job_contains_submission_no_job_settings(mocker: MockerFixture) -> None:
    approver_instance = Approver(args)
    mocker.patch("openqabot.openqa.OpenQAInterface.get_single_job", return_value=None)
    assert not approver_instance.job_contains_submission(1, 1)
