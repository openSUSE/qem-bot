# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test approve scenarios."""

from __future__ import annotations

import logging
import re
from argparse import Namespace
from typing import TYPE_CHECKING, Any

import pytest

import responses
from openqabot.approver import Approver
from openqabot.config import settings

from .helpers import (
    assert_log_messages,
    assert_submission_approved,
    assert_submission_not_approved,
    openqa_instance_url,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def with_fake_qem(mode: str) -> Any:
    def decorator(test_func: object) -> object:
        test_func = pytest.mark.qem_behavior(mode)(test_func)
        return pytest.mark.usefixtures("fake_qem")(test_func)

    return decorator


@pytest.fixture
def fake_single_submission_mocks() -> None:
    responses.add(
        responses.GET,
        re.compile(f"{settings.qem_dashboard_url}api/submission/.*"),
        json={
            "approved": False,
            "inReview": True,
            "inReviewQAM": True,
            "isActive": True,
            "number": 1,
            "rr_number": 100,
        },
    )
    responses.add(
        responses.GET,
        re.compile(f"{settings.qem_dashboard_url}api/jobs/incident/100"),
        json=[{"submission_settings": 1000, "job_id": 100001, "status": "failed"}],
    )
    responses.add(
        responses.GET,
        re.compile(f"{settings.qem_dashboard_url}api/jobs/incident/400"),
        json=[{"submission_settings": 1000, "job_id": 100000, "status": "passed"}],
    )
    responses.add(
        responses.GET,
        re.compile(r"http://instance.qa/api/v1/jobs/.*/comments"),
        json=[],
    )


@pytest.fixture
def fake_openqa_older_jobs_api() -> None:
    responses.get(
        re.compile(r"http://instance.qa/tests/.*/ajax\?previous_limit=.*&next_limit=0"),
        json={"data": []},
    )


@pytest.fixture
def fake_openqa_comment_api() -> None:
    responses.add(
        responses.GET,
        re.compile(r"http://instance.qa/api/v1/jobs/.*/comments"),
        json={"error": "job not found"},
        status=404,
    )


@pytest.fixture
def fake_responses_updating_job() -> None:
    responses.add(responses.PATCH, f"{settings.qem_dashboard_url}api/jobs/100001")


def approver(submission: int = 0) -> int:
    args = Namespace(
        dry=True,
        token="123",
        all_submissions=False,
        openqa_instance=openqa_instance_url,
        incident=submission,
        gitea_token=None,
    )
    approver = Approver(args)
    approver.client.retries = 0
    return approver()


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
def test_no_jobs(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch("openqabot.approver.get_json", return_value=[])
    approver()
    assert "SUSE:Maintenance:4:400 has at least one failed job in submission tests" in caplog.messages
    assert "Submissions to approve:" in caplog.messages
    assert "Submission approval process finished" in caplog.messages
    assert "* SUSE:Maintenance:4:400" not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_single_submission_mocks")
def test_single_submission_failed_not_approved(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        return [{"submission_settings": int(url.rsplit("/", maxsplit=1)[-1]), "job_id": 100001, "status": "failed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)
    mocker.patch("openqabot.openqa.OpenQAInterface.get_job_comments", return_value=[])

    approver(submission=1)
    assert_submission_not_approved(
        caplog.messages,
        "SUSE:Maintenance:1:100",
        "SUSE:Maintenance:1:100 has at least one failed job in submission tests",
    )
    assert "Found failed, not-ignored job http://instance.qa/t100001 for submission smelt:1" in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_single_submission_mocks")
def test_single_submission_passed_is_approved(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        return [{"submission_settings": int(url.rsplit("/", maxsplit=1)[-1]), "job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)

    approver(submission=4)
    assert_submission_approved(caplog.messages, "SUSE:Maintenance:4:400")


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs")
def test_all_passed(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    mocker.patch("openqabot.approver.get_json", return_value=[{"job_id": 100000, "status": "passed"}])

    assert approver() == 0
    expected = [
        "* SUSE:Maintenance:1:100",
        "* SUSE:Maintenance:2:200",
        "* SUSE:Maintenance:3:300",
        "* SUSE:Maintenance:4:400",
        "Submissions to approve:",
        "Submission approval process finished",
    ]
    assert_log_messages(caplog.messages, expected)


@responses.activate
@with_fake_qem("aggr")
@pytest.mark.usefixtures("fake_two_passed_jobs")
def test_sub_passed_aggr_without_results(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    mocker.patch("openqabot.approver.get_json", return_value=[{"job_id": 100000, "status": "passed"}])

    assert approver() == 0
    expected = [
        "No aggregate test results found for SUSE:Maintenance:1:100",
        "No aggregate test results found for SUSE:Maintenance:2:200",
        "No aggregate test results found for SUSE:Maintenance:3:300",
        "Starting approving submissions in OBS or Gitea…",
        "Submissions to approve:",
        "* SUSE:Maintenance:4:400",
        "Submission approval process finished",
    ]
    assert_log_messages(caplog.messages, expected)


@responses.activate
@with_fake_qem("inc")
@pytest.mark.usefixtures("fake_two_passed_jobs")
def test_sub_without_results(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    mocker.patch("openqabot.approver.get_json", return_value=[{"job_id": 100000, "status": "passed"}])

    assert approver() == 0
    expected = [
        "Starting approving submissions in OBS or Gitea…",
        "Submissions to approve:",
        "Submission approval process finished",
    ]
    assert_log_messages(caplog.messages, expected)
    assert "* SUSE:Maintenance" not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs", "fake_openqa_comment_api", "fake_responses_updating_job")
def test_one_submission_failed(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    # Mock dashboard results: Submission 1 fails, others pass
    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "api/jobs/incident/1000" in url:
            return [
                {"job_id": 100000, "status": "passed"},
                {"job_id": 100001, "status": "failed"},
                {"job_id": 100002, "status": "passed"},
            ]
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)

    assert approver() == 0
    expected = [
        "SUSE:Maintenance:1:100 has at least one failed job in submission tests",
        "Found failed, not-ignored job http://instance.qa/t100001 for submission smelt:1",
        "* SUSE:Maintenance:2:200",
        "* SUSE:Maintenance:3:300",
        "* SUSE:Maintenance:4:400",
        "Submissions to approve:",
        "Submission approval process finished",
    ]
    assert_log_messages(caplog.messages, expected)


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures(
    "fake_two_passed_jobs",
    "fake_openqa_comment_api",
    "fake_responses_updating_job",
    "fake_openqa_older_jobs_api",
)
def test_one_aggr_failed(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    # Mock dashboard results: Aggregate jobs for Submission 2 fail, others pass
    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "api/jobs/update/2000" in url:
            return [
                {"job_id": 100000, "status": "passed"},
                {"job_id": 100001, "status": "failed"},
                {"job_id": 100002, "status": "passed"},
            ]
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)

    assert approver() == 0
    expected = [
        "SUSE:Maintenance:2:200 has at least one failed job in aggregate tests",
        "Found failed, not-ignored job http://instance.qa/t100001 for submission smelt:2",
        "* SUSE:Maintenance:1:100",
        "* SUSE:Maintenance:3:300",
        "* SUSE:Maintenance:4:400",
        "Submissions to approve:",
        "Submission approval process finished",
    ]
    assert_log_messages(caplog.messages, expected)
