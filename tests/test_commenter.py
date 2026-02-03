# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test commenter."""

from __future__ import annotations

import logging
from argparse import Namespace
from typing import TYPE_CHECKING, Any, Callable
from unittest.mock import MagicMock, Mock

import pytest

from openqabot.commenter import Commenter
from openqabot.config import DEFAULT_SUBMISSION_TYPE
from openqabot.errors import NoResultsError
from openqabot.types.submission import Submission
from openqabot.types.types import ArchVer

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def make_job() -> Callable[..., dict[str, str | int]]:
    def _make_job(**overrides: Any) -> dict[str, str | int]:
        defaults = {
            "job_id": 1,
            "name": "test_job",
            "status": "passed",
            "job_group": "foo",
            "flavor": "test-flavor",
            "version": "something",
            "group_id": 42,
            "distri": "slowroll",
            "build": "12.34",
        }
        return {**defaults, **overrides}

    return _make_job


@pytest.fixture
def make_comment_api() -> Callable[..., MagicMock]:
    def _make_comment_api(
        comments: list | None = None,
        comment_find_results: list[tuple] | None = None,
        marker: str = "comment 1\ncomment 2\ncomment 3",
    ) -> MagicMock:
        mock = MagicMock()
        mock.get_comments.return_value = comments
        mock.add_marker.return_value = marker
        mock.truncate.return_value = marker
        mock.comment_find.side_effect = comment_find_results or [(None, None)]
        return mock

    return _make_comment_api


@pytest.fixture
def mock_args() -> Namespace:
    return Namespace(dry=True, token="test_token")


@pytest.fixture
def mock_submission_smelt() -> Mock:
    mock_submission = Mock(spec=Submission)
    mock_submission.id = 1
    mock_submission.type = DEFAULT_SUBMISSION_TYPE
    mock_submission.revisions = {}
    return mock_submission


@pytest.fixture
def mock_submission_smelt_with_revisions() -> Mock:
    mock_submission = Mock(spec=Submission)
    mock_submission.id = 2
    mock_submission.type = DEFAULT_SUBMISSION_TYPE
    mock_submission.revisions = {
        ArchVer("x86_64", "15-SP4"): 12345,
        ArchVer("aarch64", "15-SP4"): 12346,
    }
    return mock_submission


@pytest.fixture
def commenter_setup(mocker: MockerFixture) -> dict[str, MagicMock]:
    mock_client = mocker.patch("openqabot.commenter.OpenQAInterface")
    mock_get_subs = mocker.patch("openqabot.commenter.get_submissions")
    mocker.patch("openqabot.commenter.osc.conf.get_config")
    mock_comment_api = mocker.patch("openqabot.commenter.CommentAPI")
    return {
        "client": mock_client,
        "get_submissions": mock_get_subs,
        "comment_api": mock_comment_api,
    }


def test_commenter_init(commenter_setup: dict[str, MagicMock], mock_args: Namespace) -> None:
    c = Commenter(mock_args)
    assert c.dry
    assert c.token == {"Authorization": "Token test_token"}
    assert c.client == commenter_setup["client"].return_value


def test_commenter_call(
    mock_args: Namespace,
    caplog: pytest.LogCaptureFixture,
    mocker: MockerFixture,
    commenter_setup: dict[str, MagicMock],
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.commenter")
    mock_submission = mocker.MagicMock(spec=Submission)

    mock_submission.id = 1
    mock_submission.type = "maintenance"
    mock_submission.__str__.return_value = "maintenance:1"
    commenter_setup["get_submissions"].return_value = [mock_submission]

    c = Commenter(mock_args)
    assert c() == 0
    assert "Submission maintenance:1 skipped: Not a SMELT incident (type: maintenance)" in caplog.text


def test_commenter_call_value_error_submission_results(
    mocker: MockerFixture,
    mock_args: Namespace,
    mock_submission_smelt: Mock,
    caplog: pytest.LogCaptureFixture,
    commenter_setup: dict[str, MagicMock],
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.commenter")
    commenter_setup["get_submissions"].return_value = [mock_submission_smelt]

    mocker.patch("openqabot.commenter.get_submission_results", side_effect=ValueError("get_submission_results error"))

    c = Commenter(mock_args)
    assert c() == 0
    assert "get_submission_results error" in caplog.text


def test_commenter_call_value_error_aggregate_results(
    mock_args: Namespace,
    mock_submission_smelt: Mock,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    commenter_setup: dict[str, MagicMock],
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.commenter")
    commenter_setup["get_submissions"].return_value = [mock_submission_smelt]
    mocker.patch("openqabot.commenter.get_submission_results", return_value=0)
    mocker.patch("openqabot.commenter.get_aggregate_results", side_effect=ValueError("get_aggregate_results error"))

    c = Commenter(mock_args)
    assert c() == 0
    assert "get_aggregate_results error" in caplog.text


def test_commenter_call_no_results_error_submission_results(
    mocker: MockerFixture,
    mock_args: Namespace,
    mock_submission_smelt: Mock,
    caplog: pytest.LogCaptureFixture,
    commenter_setup: dict[str, MagicMock],
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.commenter")
    commenter_setup["get_submissions"].return_value = [mock_submission_smelt]
    mocker.patch("openqabot.commenter.get_submission_results", side_effect=NoResultsError("No submission results"))

    c = Commenter(mock_args)
    assert c() == 0
    assert "No submission results" in caplog.text


def test_commenter_call_running_jobs(
    mocker: MockerFixture,
    mock_args: Namespace,
    mock_submission_smelt: Mock,
    caplog: pytest.LogCaptureFixture,
    make_job: Callable,
    *,
    commenter_setup: dict[str, MagicMock],
) -> None:
    caplog.set_level(logging.INFO, logger="bot.commenter")
    mock_submission_smelt.rr = 274060
    commenter_setup["get_submissions"].return_value = [mock_submission_smelt]
    commenter_setup["client"].return_value.openqa.baseurl = "https://openqa.opensuse.org"
    mocker.patch(
        "openqabot.commenter.get_submission_results", return_value=[make_job(name="test_running", status="running")]
    )
    mocker.patch("openqabot.commenter.get_aggregate_results", return_value=[])
    mock_osc_comment = mocker.patch.object(Commenter, "osc_comment")

    c = Commenter(mock_args)
    assert c() == 0
    assert "Postponing comment for" in caplog.text
    assert mock_osc_comment.call_args[0][2] == "none"


def test_commenter_call_failed_jobs(
    mocker: MockerFixture,
    mock_args: Namespace,
    mock_submission_smelt: Mock,
    caplog: pytest.LogCaptureFixture,
    make_job: Callable,
    *,
    commenter_setup: dict[str, MagicMock],
) -> None:
    caplog.set_level(logging.INFO, logger="bot.commenter")
    mock_submission_smelt.rr = 274060
    commenter_setup["get_submissions"].return_value = [mock_submission_smelt]
    commenter_setup["client"].return_value.openqa.baseurl = "https://openqa.opensuse.org"
    mocker.patch(
        "openqabot.commenter.get_submission_results", return_value=[make_job(name="test_failed", status="failed")]
    )
    mocker.patch("openqabot.commenter.get_aggregate_results", return_value=[])
    mock_osc_comment = mocker.patch.object(Commenter, "osc_comment")

    c = Commenter(mock_args)
    assert c() == 0
    assert "At least one job failed" in caplog.text
    assert mock_osc_comment.call_args[0][2] == "failed"


def test_commenter_call_passed_jobs(
    mocker: MockerFixture,
    mock_args: Namespace,
    mock_submission_smelt: Mock,
    commenter_setup: dict[str, MagicMock],
) -> None:
    mock_submission_smelt.rr = 274060
    commenter_setup["get_submissions"].return_value = [mock_submission_smelt]
    mocker.patch(
        "openqabot.commenter.get_submission_results",
        return_value=[{"job_id": 1, "name": "test_passed", "status": "passed"}],
    )
    mocker.patch("openqabot.commenter.get_aggregate_results", return_value=[])
    mock_osc_comment = mocker.patch.object(Commenter, "osc_comment")

    c = Commenter(mock_args)
    assert c() == 0
    assert mock_osc_comment.call_args[0][2] == "passed"


@pytest.mark.usefixtures("commenter_setup")
def test_osc_comment_no_request(
    mock_args: Namespace,
    mock_submission_smelt: Mock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.commenter")
    mock_submission_smelt.rr = None
    c = Commenter(mock_args)
    c.osc_comment(mock_submission_smelt, "Test message", "passed")
    assert "Comment skipped for submission" in caplog.text


@pytest.mark.usefixtures("commenter_setup")
def test_osc_comment_no_msg(
    mock_args: Namespace,
    mock_submission_smelt: Mock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.commenter")
    mock_submission_smelt.rr = 274060
    c = Commenter(mock_args)
    c.osc_comment(mock_submission_smelt, "", "")
    assert "Skipping empty comment" in caplog.text


def test_osc_comment_dry_run(
    mock_args: Namespace,
    mock_submission_smelt: Mock,
    caplog: pytest.LogCaptureFixture,
    make_comment_api: Callable,
    commenter_setup: dict[str, MagicMock],
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.commenter")
    mock_submission_smelt.rr = 274060
    comment_api = make_comment_api(comment_find_results=[(None, None), (None, None)])
    commenter_setup["comment_api"].return_value = comment_api

    c = Commenter(mock_args)
    c.osc_comment(mock_submission_smelt, "Test message", "passed")
    assert "Would write comment to request" in caplog.text
    assert not comment_api.add_comment.called


def test_osc_comment_with_revision(
    mock_args: Namespace,
    mock_submission_smelt_with_revisions: Mock,
    caplog: pytest.LogCaptureFixture,
    make_comment_api: Callable,
    commenter_setup: dict[str, MagicMock],
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.commenter")
    mock_submission_smelt_with_revisions.rr = 274060
    comment_api = make_comment_api(comment_find_results=[(None, None), (None, None)])
    commenter_setup["comment_api"].return_value = comment_api

    c = Commenter(mock_args)
    c.osc_comment(mock_submission_smelt_with_revisions, "Test message", "passed")
    assert "Would write comment to request" in caplog.text
    assert not comment_api.add_comment.called


def test_osc_comment_no_comment(
    mock_args: Namespace,
    mock_submission_smelt: Mock,
    caplog: pytest.LogCaptureFixture,
    make_comment_api: Callable,
    commenter_setup: dict[str, MagicMock],
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.commenter")
    mock_submission_smelt.rr = 274060
    commenter_setup["comment_api"].return_value = make_comment_api(comment_find_results=[(None, None), (None, None)])

    c = Commenter(mock_args)
    c.osc_comment(mock_submission_smelt, "Test message", "passed")
    assert "No comment with this state, looking without the state filter" in caplog.text
    assert "No previous comment found to replace" in caplog.text


def test_osc_comment_similar_exists(
    mock_args: Namespace,
    mock_submission_smelt: Mock,
    caplog: pytest.LogCaptureFixture,
    make_comment_api: Callable,
    commenter_setup: dict[str, MagicMock],
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.commenter")
    mock_submission_smelt.rr = 274060
    existing_comment = {"id": 42, "comment": "comment 1\ncomment 2\ncomment 3"}
    commenter_setup["comment_api"].return_value = make_comment_api(
        comments=[existing_comment], comment_find_results=[(existing_comment, None)]
    )

    c = Commenter(mock_args)
    c.osc_comment(mock_submission_smelt, "Test message", "passed")
    assert "Previous comment is too similar" in caplog.text
    assert not commenter_setup["comment_api"].return_value.add_comment.called


def test_osc_comment_delete_existing_not_similar_not_dry(
    mock_args: Namespace,
    mock_submission_smelt: Mock,
    make_comment_api: Callable,
    commenter_setup: dict[str, MagicMock],
) -> None:
    mock_args.dry = False
    mock_submission_smelt.rr = 274060
    existing_comment = {"id": 42, "comment": "foo bar"}
    comment_api = make_comment_api(comments=[existing_comment], comment_find_results=[(existing_comment, None)])
    commenter_setup["comment_api"].return_value = comment_api

    c = Commenter(mock_args)
    c.osc_comment(mock_submission_smelt, "Test message", "passed")
    comment_api.delete.assert_called_once_with(42)
    comment_api.add_comment.assert_called_once()


def test_osc_comment_replace_not_dry(
    mock_args: Namespace,
    mock_submission_smelt: Mock,
    make_comment_api: Callable,
    commenter_setup: dict[str, MagicMock],
) -> None:
    mock_args.dry = False
    mock_submission_smelt.rr = 274060
    existing_comment = {"id": 42, "comment": "Old comment"}
    comment_api = make_comment_api(
        comments=[existing_comment], comment_find_results=[(None, None), (existing_comment, None)]
    )
    commenter_setup["comment_api"].return_value = comment_api

    c = Commenter(mock_args)
    c.osc_comment(mock_submission_smelt, "Test message", "passed")
    comment_api.delete.assert_called_once_with(42)
    comment_api.add_comment.assert_called_once()


def test_osc_comment_replace_dry_run(
    mock_args: Namespace,
    mock_submission_smelt: Mock,
    caplog: pytest.LogCaptureFixture,
    make_comment_api: Callable,
    commenter_setup: dict[str, MagicMock],
) -> None:
    caplog.set_level(logging.INFO, logger="bot.commenter")
    mock_submission_smelt.rr = 274060
    existing_comment = {"id": 42, "comment": "Old comment"}
    comment_api = make_comment_api(
        comments=[existing_comment],
        comment_find_results=[(None, None), (existing_comment, None)],
        marker="comment 1\ncomment 2",
    )
    commenter_setup["comment_api"].return_value = comment_api

    c = Commenter(mock_args)
    c.osc_comment(mock_submission_smelt, "Test message", "passed")
    assert "Would delete comment 42" in caplog.text
    assert "Would write comment to request" in caplog.text
    assert not comment_api.delete.called
    assert not comment_api.add_comment.called


def test_summarize_message_one_passed_job(
    mock_args: Namespace,
    make_job: Callable,
    commenter_setup: dict[str, MagicMock],
) -> None:
    commenter_setup["client"].return_value.openqa.baseurl = "https://openqa.opensuse.org"
    c = Commenter(mock_args)
    result = c.summarize_message([make_job()])
    assert "foo" in result
    assert "test-flavor" in result
    assert "1 tests passed" in result


def test_summarize_message_multiple_jobs_same_group(
    mock_args: Namespace,
    make_job: Callable,
    commenter_setup: dict[str, MagicMock],
) -> None:
    commenter_setup["client"].return_value.openqa.baseurl = "https://openqa.opensuse.org"
    c = Commenter(mock_args)
    result = c.summarize_message([make_job(name="test_job_1"), make_job(job_id=2, name="test_job_2")])
    assert "foo" in result
    assert "test-flavor" in result
    assert "2 tests passed" in result


def test_summarize_message_job_status_none(
    mock_args: Namespace,
    make_job: Callable,
    commenter_setup: dict[str, MagicMock],
) -> None:
    commenter_setup["client"].return_value.openqa.baseurl = "https://openqa.opensuse.org"
    c = Commenter(mock_args)
    result = c.summarize_message([make_job(status="none")])
    assert "foo" in result
    assert "1 unfinished tests" in result
