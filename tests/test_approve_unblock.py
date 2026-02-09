# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test approve unblock."""

from __future__ import annotations

import logging
import re
from argparse import Namespace
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

import responses
from openqabot.approver import Approver
from openqabot.config import settings

from .helpers import (
    add_two_passed_response,
    assert_log_messages,
    openqa_instance_url,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@dataclass(frozen=True)
class CommentFormatTestCase:
    """Test case for comment format."""

    comment_text: str
    description: str


def with_fake_qem(mode: str) -> Any:
    def decorator(test_func: object) -> object:
        test_func = pytest.mark.qem_behavior(mode)(test_func)
        return pytest.mark.usefixtures("fake_qem")(test_func)

    return decorator


@pytest.fixture
def fake_responses_for_unblocking_submissions_via_older_ok_result(
    request: pytest.FixtureRequest,
) -> None:
    responses.add(
        responses.GET,
        f"{settings.qem_dashboard_url}api/jobs/update/20005",
        json=[
            {"job_id": 100000, "status": "passed"},
            {"job_id": 100002, "status": "failed"},
            {"job_id": 100003, "status": "passed"},
        ],
    )
    add_two_passed_response()
    responses.add(
        responses.GET,
        url="http://instance.qa/api/v1/jobs/100002/comments",
        json=[{"text": "@review:acceptable_for:submission_555:foo"}],
    )
    responses.add(
        responses.GET,
        re.compile(r"http://instance.qa/tests/.*/ajax\?previous_limit=.*&next_limit=0"),
        json={
            "data": [
                {"build": "20240115-1", "id": 100002, "result": "failed"},
                {"build": "20240114-1", "id": 100004, "result": "failed"},
                {"build": "20251201-1", "id": 100005, "result": "softfailed"},
            ],
        },
    )
    responses.add(
        responses.GET,
        re.compile(r"http://instance.qa/api/v1/jobs/.*"),
        json={
            "job": {
                "settings": {
                    "BASE_TEST_REPOS": f"http://download.suse.de/ibs/SUSE:/Maintenance:/1111/SUSE_Updates_SLE-Module-Basesystem_15-SP5_x86_64/,http://download.suse.de/ibs/SUSE:/Maintenance:/{request.param}/SUSE_Updates_SLE-Module-Basesystem_15-SP5_x86_64/"
                },
            },
        },
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
def fake_responses_for_unblocking_submissions_via_openqa_comments(
    request: pytest.FixtureRequest,
) -> None:
    params = request.param
    submission = params["submission"]
    responses.add(
        responses.GET,
        f"{settings.qem_dashboard_url}api/jobs/update/20005",
        json=[
            {"job_id": 100000, "status": "passed"},
            {"job_id": 100002, "status": "failed"},
            {"job_id": 100003, "status": "failed"},
            {"job_id": 100004, "status": "failed"},
        ],
    )
    add_two_passed_response()
    for job_id in params.get("not_acceptable_job_ids", []):
        responses.get(
            url=f"http://instance.qa/api/v1/jobs/{job_id}/comments",
            json=[{"text": ""}],
        )
    for job_id in params.get("acceptable_job_ids", [100002, 100003, 100004]):
        responses.get(
            url=f"http://instance.qa/api/v1/jobs/{job_id}/comments",
            json=[{"text": f"@review:acceptable_for:submission_{submission}:foo"}],
        )


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
@pytest.mark.parametrize(
    "fake_responses_for_unblocking_submissions_via_openqa_comments",
    [{"submission": 2}],
    indirect=True,
)
@pytest.mark.usefixtures(
    "fake_responses_for_unblocking_submissions_via_openqa_comments",
    "fake_openqa_comment_api",
    "fake_openqa_older_jobs_api",
)
def test_approval_unblocked_via_openqa_comment(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "api/jobs/incident/2000" in url:
            return [
                {"job_id": 100000, "status": "passed"},
                {"job_id": 100002, "status": "failed"},
                {"job_id": 100003, "status": "failed"},
                {"job_id": 100004, "status": "failed"},
            ]
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)
    comments_return_value = [{"text": "@review:acceptable_for:submission_2:foo"}]
    mocker.patch("openqabot.openqa.OpenQAInterface.get_job_comments", return_value=comments_return_value)
    mock_patch = mocker.patch("openqabot.approver.patch")

    assert approver() == 0
    expected = [
        "* SUSE:Maintenance:2:200",
        "Ignoring failed job http://instance.qa/t100002 for submission smelt:2 (manually marked as acceptable)",
    ]
    assert_log_messages(caplog.messages, expected)

    expected_url = "api/jobs/100002/remarks?text=acceptable_for&incident_number=2"
    mock_patch.assert_any_call(expected_url, headers=mocker.ANY)


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.parametrize(
    "fake_responses_for_unblocking_submissions_via_openqa_comments",
    [
        {
            "submission": 2,
            "not_acceptable_job_ids": [100003],
            "acceptable_job_ids": [100002, 100004],
        },
    ],
    indirect=True,
)
@pytest.mark.usefixtures(
    "fake_responses_for_unblocking_submissions_via_openqa_comments",
    "fake_openqa_comment_api",
    "fake_openqa_older_jobs_api",
)
def test_all_jobs_marked_as_acceptable_for_via_openqa_comment(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "api/jobs/incident/2000" in url:
            return [
                {"job_id": 100000, "status": "passed"},
                {"job_id": 100002, "status": "failed"},
                {"job_id": 100003, "status": "failed"},
                {"job_id": 100004, "status": "failed"},
            ]
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)

    def mock_get_job_comments(job_id: int) -> list[dict[str, str]]:
        if job_id in {100002, 100004}:
            return [{"text": "@review:acceptable_for:submission_2:foo"}]
        return []

    mocker.patch("openqabot.openqa.OpenQAInterface.get_job_comments", side_effect=mock_get_job_comments)
    mock_patch = mocker.patch("openqabot.approver.patch")

    assert approver() == 0
    expected = [
        "Ignoring failed job http://instance.qa/t100002 for submission smelt:2 (manually marked as acceptable)",
    ]
    assert_log_messages(caplog.messages, expected)
    assert "* SUSE:Maintenance:2:200" not in caplog.messages, "submission not approved due to one unacceptable failure"

    mock_patch.assert_any_call("api/jobs/100002/remarks?text=acceptable_for&incident_number=2", headers=mocker.ANY)
    mock_patch.assert_any_call("api/jobs/100004/remarks?text=acceptable_for&incident_number=2", headers=mocker.ANY)

    for call in mock_patch.call_args_list:
        assert "100003" not in call[0][0]
        assert "100000" not in call[0][0]


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.parametrize(
    "fake_responses_for_unblocking_submissions_via_openqa_comments",
    [{"submission": 22}],
    indirect=True,
)
@pytest.mark.usefixtures(
    "fake_responses_for_unblocking_submissions_via_openqa_comments",
    "fake_openqa_comment_api",
    "fake_openqa_older_jobs_api",
)
def test_approval_still_blocked_if_openqa_comment_not_relevant(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "update/2000" in url:
            return [
                {"job_id": 100000, "status": "passed"},
                {"job_id": 100002, "status": "failed"},
            ]
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)
    comments_return_value = [{"text": "@review:acceptable_for:submission_22:foo"}]
    mocker.patch("openqabot.openqa.OpenQAInterface.get_job_comments", return_value=comments_return_value)

    assert approver() == 0
    assert "* SUSE:Maintenance:2:200" not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.parametrize("fake_responses_for_unblocking_submissions_via_older_ok_result", [2], indirect=True)
@pytest.mark.usefixtures("fake_responses_for_unblocking_submissions_via_older_ok_result")
@pytest.mark.parametrize(
    ("mock_json", "approved"),
    [
        ({"status": "passed"}, True),
        ({"error": "Job not found"}, False),
    ],
    ids=["job_passed", "job_not_found"],
)
def test_approval_via_openqa_older_ok_job(
    caplog: pytest.LogCaptureFixture, mock_json: dict, *, approved: bool, mocker: MockerFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "update/2000" in url:
            return [{"job_id": 100002, "status": "failed"}]
        if url in {f"{settings.qem_dashboard_url}api/jobs/100005", "api/jobs/100005"}:
            return mock_json
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)
    mocker.patch(
        "openqabot.openqa.OpenQAInterface.get_older_jobs",
        return_value={
            "data": [
                {"build": "20240115-1", "id": 100002, "result": "failed"},
                {"build": "20240114-1", "id": 100005, "result": "passed"},
            ]
        },
    )
    mocker.patch(
        "openqabot.openqa.OpenQAInterface.get_single_job",
        return_value={"settings": {"BASE_TEST_REPOS": "Maintenance:/2/"}},
    )

    assert approver() == 0

    log_message = "* SUSE:Maintenance:2:200"
    assert log_message in caplog.messages if approved else log_message not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.parametrize("fake_responses_for_unblocking_submissions_via_older_ok_result", [2], indirect=True)
@pytest.mark.usefixtures("fake_responses_for_unblocking_submissions_via_older_ok_result")
def test_approval_still_blocked_via_openqa_older_ok_job_because_not_in_dashboard(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "update/2000" in url:
            return [{"job_id": 100002, "status": "failed"}]
        if url in {f"{settings.qem_dashboard_url}api/jobs/100005", "api/jobs/100005"}:
            return {"error": "Job not found"}
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)
    mocker.patch(
        "openqabot.openqa.OpenQAInterface.get_older_jobs",
        return_value={
            "data": [
                {"build": "20240115-1", "id": 100002, "result": "failed"},
                {"build": "20240114-1", "id": 100005, "result": "passed"},
            ]
        },
    )
    mocker.patch(
        "openqabot.openqa.OpenQAInterface.get_single_job",
        return_value={"settings": {"BASE_TEST_REPOS": "Maintenance:/2/"}},
    )

    assert approver() == 0
    assert "* SUSE:Maintenance:2:200" not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.parametrize(
    "fake_responses_for_unblocking_submissions_via_older_ok_result",
    [2222],
    indirect=True,
)
@pytest.mark.usefixtures("fake_responses_for_unblocking_submissions_via_older_ok_result")
def test_approval_still_blocked_if_openqa_older_job_dont_include_submission(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    assert approver() == 0
    assert "* SUSE:Maintenance:2:200" not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.parametrize(
    "case",
    [
        CommentFormatTestCase(
            comment_text="\r\r@review:acceptable_for:submission_2:foo\r",
            description="with carriage returns",
        ),
        CommentFormatTestCase(
            comment_text="Some irrelevant text\n@review:acceptable_for:submission_2:foo",
            description="with text before @review",
        ),
        CommentFormatTestCase(
            comment_text="@review:acceptable_for:submission_2:foo\nSome extra text",
            description="with trailing characters",
        ),
        CommentFormatTestCase(
            comment_text="\x0c@review:acceptable_for:submission_2:foo",
            description="with non-printable character",
        ),
    ],
    ids=lambda c: c.description,
)
@pytest.mark.usefixtures("fake_openqa_older_jobs_api")
def test_approval_unblocked_with_various_comment_formats(
    case: CommentFormatTestCase, caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mock_get_json = mocker.patch("openqabot.approver.get_json")

    def side_effect_get_json(url: str, **_kwargs: Any) -> Any:
        if "api/jobs/incident/2000" in url:
            return [
                {"job_id": 100000, "status": "passed"},
                {"job_id": 100002, "status": "failed"},
                {"job_id": 100003, "status": "passed"},
            ]
        return [{"status": "passed"}, {"status": "passed"}]

    mock_get_json.side_effect = side_effect_get_json

    mocker.patch(
        "openqabot.openqa.OpenQAInterface.get_job_comments",
        return_value=[{"text": case.comment_text}],
    )
    mock_patch = mocker.patch("openqabot.approver.patch")

    assert approver() == 0
    assert "* SUSE:Maintenance:2:200" in caplog.messages
    assert (
        "Ignoring failed job http://instance.qa/t100002 for submission smelt:2 (manually marked as acceptable)"
        in caplog.messages
    )

    expected_url = "api/jobs/100002/remarks?text=acceptable_for&incident_number=2"
    mock_patch.assert_called_once_with(expected_url, headers=mocker.ANY)
