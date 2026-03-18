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
from openqabot.loader.qem import JobAggr
from openqabot.utc import UTC

from .helpers import args, make_approver_args

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
    mocker.patch("openqabot.approver.dashboard.patch", side_effect=f_patch)
    approver_instance.mark_job_as_acceptable_for_submission(1, 1)
    assert "Unable to mark job 1 as acceptable for submission smelt:1" in caplog.text


@pytest.mark.parametrize(
    "json_data", [pytest.param(None, id="no_qam_data"), pytest.param({"status": "failed"}, id="status_not_passed")]
)
def test_validate_job_qam_no_qam_data(json_data: dict, mocker: MockerFixture) -> None:
    approver_instance = Approver(args)
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=json_data)
    assert not approver_instance.validate_job_qam(1)


@pytest.mark.parametrize(
    ("job", "log_message"),
    [
        ({"build": "invalid-date", "result": "passed", "id": 123}, "Could not parse build date"),
        ({"build": "20200101-1", "result": "passed", "id": 123}, "Older jobs are too old"),
    ],
)
def test_was_older_job_ok_returns_none(job: dict, log_message: str, caplog: pytest.LogCaptureFixture) -> None:
    approver_instance = Approver(args)
    oldest_build_usable = datetime.now(UTC) - timedelta(days=1)

    caplog.set_level(logging.INFO)
    assert not approver_instance.was_older_job_ok(1, 1, job, oldest_build_usable)
    assert any(log_message in m for m in caplog.messages)


@pytest.mark.parametrize(
    ("older_jobs_data", "log_message"),
    [
        pytest.param(
            [{"build": "20240101XY", "result": "failed", "id": 123}],
            "No suitable older jobs found",
            id="no_suitable_older_jobs",
        ),
        pytest.param(
            [{"build": "invalid-date"}],
            "Could not parse build date",
            id="invalid_date",
        ),
        pytest.param(
            [],
            "Cannot find older jobs for not-ok job 1",
            id="empty_data",
        ),
    ],
)
def test_was_ok_before_no_suitable_older_jobs(
    older_jobs_data: list[dict], log_message: str, caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    approver_instance = Approver(args)
    caplog.set_level(logging.INFO)
    mocker.patch("openqabot.openqa.OpenQAInterface.get_older_jobs", return_value={"data": older_jobs_data})
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


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_latest_passes_approves(mocker: MockerFixture) -> None:
    """Test that when a failed job is cloned and the clone passes, approval succeeds."""
    mock_job_results = [
        {"job_id": 20252358, "status": "failed", "name": "scenario1"},
        {"job_id": 20256065, "status": "passed", "name": "scenario1"},
    ]
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=mock_job_results)
    approver = Approver(make_approver_args())
    mock_aggr = JobAggr(id=1000, aggregate=False, with_aggregate=True)
    result = approver.get_jobs(mock_aggr, "api/jobs/incident/", 1)
    assert result is True


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_latest_fails_blocks(mocker: MockerFixture) -> None:
    """Test that when the latest job fails, approval is blocked."""
    mock_job_results = [
        {"job_id": 20252358, "status": "passed", "name": "scenario1"},
        {"job_id": 20256065, "status": "failed", "name": "scenario1"},
    ]
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=mock_job_results)
    mocker.patch.object(Approver, "was_ok_before", return_value=False)
    mocker.patch.object(Approver, "is_job_marked_acceptable_for_submission", return_value=False)
    approver = Approver(make_approver_args())
    mock_aggr = JobAggr(id=1000, aggregate=False, with_aggregate=True)
    result = approver.get_jobs(mock_aggr, "api/jobs/incident/", 1)
    assert result is False


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_different_scenarios(mocker: MockerFixture) -> None:
    """Test that different scenarios are handled independently."""
    mock_job_results = [
        {"job_id": 20252358, "status": "failed", "name": "sc1"},
        {"job_id": 20256065, "status": "passed", "name": "sc1"},
        {"job_id": 20252359, "status": "failed", "name": "sc2"},
        {"job_id": 20256066, "status": "passed", "name": "sc2"},
    ]
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=mock_job_results)
    approver = Approver(make_approver_args())
    mock_aggr = JobAggr(id=1000, aggregate=False, with_aggregate=True)
    result = approver.get_jobs(mock_aggr, "api/jobs/incident/", 1)
    assert result is True


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_two_scenarios_one_fails_blocks(mocker: MockerFixture) -> None:
    """Test that if one scenario fails (even with older ID), approval is blocked."""
    mock_job_results = [
        {"job_id": 1000, "status": "passed", "name": "scenario1"},
        {"job_id": 500, "status": "failed", "name": "scenario2"},
    ]
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=mock_job_results)
    mocker.patch.object(Approver, "is_job_marked_acceptable_for_submission", return_value=False)
    approver = Approver(make_approver_args())
    mock_aggr = JobAggr(id=1000, aggregate=False, with_aggregate=True)
    result = approver.get_jobs(mock_aggr, "api/jobs/incident/", 1)
    assert result is False


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_fallback_to_other_urls(mocker: MockerFixture) -> None:
    """Test that non-incident URLs return fallback results."""
    mock_job_results = [
        {"job_id": 20252358, "status": "failed", "name": "sc1"},
        {"job_id": 20256065, "status": "passed", "name": "sc1"},
    ]
    fallback_results = [{"job_id": 100000, "status": "passed"}]

    def mock_get_json(url: str, **_kwargs: object) -> list[dict]:
        return mock_job_results if "incident" in url else fallback_results

    mocker.patch("openqabot.approver.dashboard.get_json", side_effect=mock_get_json)
    approver = Approver(make_approver_args())
    mock_aggr = JobAggr(id=1000, aggregate=False, with_aggregate=True)
    result_incident = approver.get_jobs(mock_aggr, "api/jobs/incident/", 1)
    result_update = approver.get_jobs(mock_aggr, "api/jobs/update/", 1)
    assert result_incident is True
    assert result_update is True


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_empty_results(mocker: MockerFixture) -> None:
    """Test that None is returned when no job results are found."""
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=[])
    approver = Approver(make_approver_args())
    mock_aggregates = [JobAggr(id=1, aggregate=False, with_aggregate=True)]
    result = approver.get_jobs(mock_aggregates[0], "api/jobs/update/", 1)
    assert result is None


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_error_results(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    """Test that None is returned when job results contain error."""
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mock_job_results = {"error": "Not found"}
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=mock_job_results)
    approver = Approver(make_approver_args())
    mock_aggregates = [JobAggr(id=1, aggregate=False, with_aggregate=True)]
    result = approver.get_jobs(mock_aggregates[0], "api/jobs/update/", 1)
    assert result is None
    assert any("Unexpected job results format" in msg for msg in caplog.messages)


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_jobs_without_job_id(mocker: MockerFixture) -> None:
    """Test that jobs without job_id are handled correctly during deduplication."""
    mock_job_results = [
        {"job_id": 100, "status": "passed", "name": "scenario1"},
        {"status": "passed", "name": "scenario2"},
    ]
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=mock_job_results)
    approver = Approver(make_approver_args())
    mock_aggregates = [JobAggr(id=1, aggregate=False, with_aggregate=True)]
    result = approver.get_jobs(mock_aggregates[0], "api/jobs/update/", 1)
    assert result is True


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_keeps_highest_job_id(mocker: MockerFixture) -> None:
    """Test that deduplication keeps highest job_id even when lower job_id comes later in list."""
    mock_job_results = [
        {"job_id": 101, "status": "passed", "name": "scenario1"},
        {"job_id": 100, "status": "failed", "name": "scenario1"},
    ]
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=mock_job_results)
    approver = Approver(make_approver_args())
    mock_aggregates = [JobAggr(id=1, aggregate=False, with_aggregate=True)]
    result = approver.get_jobs(mock_aggregates[0], "api/jobs/update/", 1)
    assert result is True
