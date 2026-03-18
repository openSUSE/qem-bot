# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test approve scenarios."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import pytest

import responses
from openqabot.config import settings
from openqabot.loader.qem import JobAggr, SubReq

from .conftest import make_approver as approver
from .conftest import with_fake_qem
from .helpers import (
    assert_log_messages,
    assert_submission_approved,
    assert_submission_not_approved,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


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
            "project": "SUSE:Maintenance:1",
            "embargoed": False,
            "channels": ["SUSE:Updates:SLE-Module-Development-Tools:15-SP4:x86_64"],
            "packages": ["pkg"],
            "emu": False,
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
def fake_responses_updating_job() -> None:
    responses.add(responses.PATCH, f"{settings.qem_dashboard_url}api/jobs/100001")


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
def test_no_jobs(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=[])
    mocker.patch("openqabot.commenter.Commenter.comment_on_submission")
    approver()
    assert "SUSE:Maintenance:4:400 has at least one not-ok job in submission tests" in caplog.messages
    assert "Submissions to approve:" in caplog.messages
    assert "Submission approval process finished" in caplog.messages
    assert "* SUSE:Maintenance:4:400" not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_single_submission_mocks")
def test_single_submission_not_ok_not_approved(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        return [{"submission_settings": int(url.rsplit("/", maxsplit=1)[-1]), "job_id": 100001, "status": "failed"}]

    mocker.patch("openqabot.approver.dashboard.get_json", side_effect=mock_get_json)
    mocker.patch("openqabot.openqa.OpenQAInterface.get_job_comments", return_value=[])
    mock_comment = mocker.patch("openqabot.commenter.Commenter.comment_on_submission")
    approver(submission=1, comment=True)
    assert_submission_not_approved(
        caplog.messages,
        "SUSE:Maintenance:1:100",
        "SUSE:Maintenance:1:100 has at least one not-ok job in submission tests",
    )
    assert "Found not-ok, not-ignored job http://instance.qa/t100001 for submission smelt:1" in caplog.messages
    mock_comment.assert_called()
    assert any(c.args[0].rr == 100 for c in mock_comment.call_args_list)


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_single_submission_mocks")
def test_no_comment_suppresses_commenting(mocker: MockerFixture) -> None:
    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        return [{"submission_settings": int(url.rsplit("/", maxsplit=1)[-1]), "job_id": 100001, "status": "failed"}]

    mocker.patch("openqabot.approver.dashboard.get_json", side_effect=mock_get_json)
    mocker.patch("openqabot.openqa.OpenQAInterface.get_job_comments", return_value=[])
    mock_comment = mocker.patch("openqabot.commenter.Commenter.comment_on_submission")
    mock_handle_job_not_found = mocker.patch("openqabot.approver.OpenQAInterface.handle_job_not_found")
    approver(submission=1)  # default comment=False
    mock_comment.assert_not_called()
    mock_handle_job_not_found.assert_not_called()


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_single_submission_mocks")
def test_single_submission_passed_is_approved(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        return [{"submission_settings": int(url.rsplit("/", maxsplit=1)[-1]), "job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.dashboard.get_json", side_effect=mock_get_json)
    approver(submission=4)
    assert_submission_approved(caplog.messages, "SUSE:Maintenance:4:400")


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs")
def test_all_passed(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    mocker.patch("openqabot.approver.dashboard.get_json", return_value=[{"job_id": 100000, "status": "passed"}])
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

    mocker.patch("openqabot.approver.dashboard.get_json", return_value=[{"job_id": 100000, "status": "passed"}])
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

    mocker.patch("openqabot.approver.dashboard.get_json", return_value=[{"job_id": 100000, "status": "passed"}])
    assert approver() == 0
    expected = [
        "Starting approving submissions in OBS or Gitea…",
        "Submissions to approve:",
        "Submission approval process finished",
    ]
    assert_log_messages(caplog.messages, expected)
    for i in range(1, 5):
        assert f"* SUSE:Maintenance:{i}:{i}00" not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs")
def test_one_submission_failed_no_jobs(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "incident/100" in url:
            return [{"job_id": 100001, "status": "failed"}]
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.dashboard.get_json", side_effect=mock_get_json)
    mocker.patch("openqabot.openqa.OpenQAInterface.get_job_comments", return_value=[])
    mocker.patch("openqabot.commenter.Commenter.comment_on_submission")
    assert approver() == 0
    expected = [
        "Starting approving submissions in OBS or Gitea…",
        "Submissions to approve:",
        "Submission approval process finished",
    ]
    assert_log_messages(caplog.messages, expected)
    assert "* SUSE:Maintenance:1:100" not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs", "fake_openqa_comment_api", "fake_responses_updating_job")
def test_one_submission_failed_with_comment(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
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

    mocker.patch("openqabot.approver.dashboard.get_json", side_effect=mock_get_json)
    mock_comment = mocker.patch("openqabot.commenter.Commenter.comment_on_submission")
    mock_handle_job_not_found = mocker.patch("openqabot.approver.OpenQAInterface.handle_job_not_found")
    assert approver() == 0
    expected = [
        "Ignoring obsolete job http://instance.qa/t100001 for submission smelt:1",
        "* SUSE:Maintenance:1:100",
        "* SUSE:Maintenance:2:200",
        "* SUSE:Maintenance:3:300",
        "* SUSE:Maintenance:4:400",
        "Submissions to approve:",
        "Submission approval process finished",
    ]
    assert_log_messages(caplog.messages, expected)
    mock_comment.assert_not_called()
    mock_handle_job_not_found.assert_called_once_with(100001)


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
                {"job_id": 100003, "status": "failed"},
                {"job_id": 100004, "status": "passed"},
            ]
        return [{"job_id": 100000, "status": "passed"}]

    responses.add(responses.PATCH, f"{settings.qem_dashboard_url}api/jobs/100003")
    mocker.patch("openqabot.approver.dashboard.get_json", side_effect=mock_get_json)
    mock_comment = mocker.patch("openqabot.commenter.Commenter.comment_on_submission")
    mock_handle_job_not_found = mocker.patch("openqabot.approver.OpenQAInterface.handle_job_not_found")
    assert approver(comment=True) == 0
    expected = [
        "Ignoring obsolete job http://instance.qa/t100003 for submission smelt:2",
        "* SUSE:Maintenance:1:100",
        "* SUSE:Maintenance:2:200",
        "* SUSE:Maintenance:3:300",
        "* SUSE:Maintenance:4:400",
        "Submissions to approve:",
        "Submission approval process finished",
    ]
    assert_log_messages(caplog.messages, expected)
    mock_comment.assert_not_called()
    mock_handle_job_not_found.assert_called_with(100003)


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_single_submission_mocks")
def test_single_submission_not_ok_no_data(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    # Mock get_single_submission to return a SubReq without a parsed submission
    def mock_get_json(_url: str, **_kwargs: Any) -> Any:
        return [{"submission_settings": 1000, "job_id": 100001, "status": "failed"}]

    mocker.patch(
        "openqabot.approver.get_single_submission",
        return_value=[SubReq(sub=1, req=100, type="smelt", submission=None)],
    )
    mocker.patch("openqabot.approver.dashboard.get_json", side_effect=mock_get_json)
    mock_comment = mocker.patch("openqabot.commenter.Commenter.comment_on_submission")
    mock_handle_job_not_found = mocker.patch("openqabot.approver.OpenQAInterface.handle_job_not_found")
    approver(submission=1)
    assert "smelt:1 has at least one not-ok job in submission tests" in caplog.messages
    mock_comment.assert_not_called()
    mock_handle_job_not_found.assert_not_called()


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_single_submission_mocks")
def test_single_submission_aggr_not_ok_no_data(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    # Mock dashboard responses
    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "update" in url:
            return [{"submission_settings": 1000, "job_id": 100001, "status": "failed"}]
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch(
        "openqabot.approver.get_single_submission",
        return_value=[SubReq(sub=1, req=100, type="smelt", submission=None)],
    )
    mocker.patch("openqabot.approver.dashboard.get_json", side_effect=mock_get_json)
    mock_comment = mocker.patch("openqabot.commenter.Commenter.comment_on_submission")
    mocker.patch("openqabot.approver.Approver.was_ok_before", return_value=False)

    # We need s_jobs to have with_aggregate=True to reach the aggregate check
    mocker.patch(
        "openqabot.approver.get_submission_settings",
        return_value=[JobAggr(1000, aggregate=False, with_aggregate=True)],
    )
    mock_handle_job_not_found = mocker.patch("openqabot.approver.OpenQAInterface.handle_job_not_found")
    approver(submission=1)
    assert "smelt:1 has at least one not-ok job in aggregate tests" in caplog.messages
    mock_comment.assert_not_called()
    mock_handle_job_not_found.assert_not_called()


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.parametrize(
    ("job_passed", "expected_messages", "not_approved_reason"),
    [
        (
            True,
            [
                "* SUSE:Maintenance:2:200",
                "Ignoring not-ok aggregate job http://instance.qa/t100002 for submission smelt:2 due to older ok job",
            ],
            None,
        ),
        (
            False,
            ["Found not-ok, not-ignored job http://instance.qa/t100002 for submission smelt:2"],
            "SUSE:Maintenance:2:200 has at least one not-ok job in aggregate tests",
        ),
    ],
    ids=["job_passed", "job_not_passed"],
)
def test_approval_via_openqa_older_ok_job(
    caplog: pytest.LogCaptureFixture,
    mocker: MockerFixture,
    job_passed: object,
    expected_messages: list[str],
    not_approved_reason: str | None,
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "api/jobs/update/20000" in url:
            return [
                {"job_id": 100000, "status": "passed"},
                {"job_id": 100002, "status": "failed"},
            ]
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.dashboard.get_json", side_effect=mock_get_json)
    mocker.patch("openqabot.openqa.OpenQAInterface.get_job_comments", return_value=[])
    mocker.patch("openqabot.approver.Approver.was_ok_before", return_value=job_passed)
    mocker.patch("openqabot.commenter.Commenter.comment_on_submission")

    assert approver() == 0
    assert_log_messages(caplog.messages, expected_messages)
    if not_approved_reason:
        assert_submission_not_approved(caplog.messages, "SUSE:Maintenance:2:200", not_approved_reason)
        assert "* SUSE:Maintenance:2:200" not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_single_submission_mocks")
@pytest.mark.parametrize(
    ("job_results", "expected_messages", "is_approved"),
    [
        (
            [{"job_id": 100001, "status": "failed", "obsolete": True}],
            ["Ignoring obsolete job http://instance.qa/t100001 for submission smelt:1"],
            True,
        ),
        (
            [
                {"job_id": 100001, "status": "failed", "obsolete": True},
                {"job_id": 100002, "status": "failed", "obsolete": False},
            ],
            [
                "Ignoring obsolete job http://instance.qa/t100001 for submission smelt:1",
                "Found not-ok, not-ignored job http://instance.qa/t100002 for submission smelt:1",
            ],
            False,
        ),
    ],
    ids=["obsolete_only", "obsolete_and_failed"],
)
def test_approval_with_obsolete_jobs(
    caplog: pytest.LogCaptureFixture,
    mocker: MockerFixture,
    job_results: list[dict],
    expected_messages: list[str],
    *,
    is_approved: bool,
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "api/jobs/incident/1000" in url:
            return job_results
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.dashboard.get_json", side_effect=mock_get_json)
    mocker.patch("openqabot.openqa.OpenQAInterface.get_job_comments", return_value=[])
    mocker.patch("openqabot.commenter.Commenter.comment_on_submission")

    assert approver(submission=1) == 0
    assert_log_messages(caplog.messages, expected_messages)
    if is_approved:
        assert_submission_approved(caplog.messages, "SUSE:Maintenance:1:100")
    else:
        assert_submission_not_approved(
            caplog.messages,
            "SUSE:Maintenance:1:100",
            "SUSE:Maintenance:1:100 has at least one not-ok job in submission tests",
        )
