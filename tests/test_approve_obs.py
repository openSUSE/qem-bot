# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test approve OBS."""

import io
import logging
from typing import Any
from urllib.error import HTTPError

import pytest
from pytest_mock import MockerFixture

import responses
from openqabot.approver import Approver
from openqabot.config import settings
from responses import matchers

from .helpers import (
    args,
    assert_log_messages,
)


def with_fake_qem(mode: str) -> Any:
    def decorator(test_func: object) -> object:
        test_func = pytest.mark.qem_behavior(mode)(test_func)
        return pytest.mark.usefixtures("fake_qem")(test_func)

    return decorator


class ObsHTTPError(HTTPError):
    """Fake OBS HTTP error."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize the ObsHTTPError class."""
        super().__init__("http://obs.api", *args, **kwargs)


class ArbitraryObsError(Exception):
    """Fake arbitrary error."""

    def __init__(self) -> None:
        """Initialize the ArbitraryObsError class."""
        super().__init__("Arbitrary error")


@pytest.fixture
def f_osconf(mocker: MockerFixture) -> Any:
    return mocker.patch("osc.conf.get_config")


@pytest.fixture
def fake_responses_for_creating_pr_review() -> None:

    responses.add(
        responses.POST,
        "https://src.suse.de/api/v1/repos/products/SLFO/pulls/5/reviews",
        json={},
        match=[
            matchers.json_params_matcher(
                {
                    "body": f"Request accepted for 'qam-openqa' based on data in {settings.qem_dashboard_url}",
                    "commit_id": "18bfa2a23fb7985d5d0cc356474a96a19d91d2d8652442badf7f13bc07cd1f3d",
                    "comments": [],
                    "event": "APPROVED",
                },
            ),
        ],
    )


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs", "fake_responses_for_creating_pr_review", "f_osconf")
def test_403_response(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    mocker.patch("openqabot.config.settings.git_review_bot", "")
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch("osc.core.change_review_state", side_effect=ObsHTTPError(403, "Not allowed", "sd", None))
    assert Approver(args)() == 0
    assert "Received 'Not allowed'. Request 100 likely already approved, ignoring" in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs", "f_osconf")
def test_404_response(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch(
        "osc.core.change_review_state", side_effect=ObsHTTPError(404, "Not Found", None, io.BytesIO(b"review state"))
    )
    assert Approver(args)() == 1
    assert "OBS API error for request 100 (removed or server issue): Not Found - review state" in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs", "f_osconf")
def test_500_response(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch("osc.core.change_review_state", side_effect=ObsHTTPError(500, "Not allowed", "sd", None))
    assert Approver(args)() == 1
    assert "OBS API error for request 400: 500 - Not allowed" in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs", "f_osconf")
def test_osc_unknown_exception(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch("osc.core.change_review_state", side_effect=ArbitraryObsError)
    assert Approver(args)() == 1
    assert "OBS API error: Failed to approve request" in caplog.text


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs", "f_osconf")
def test_osc_all_pass(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    mocker.patch("openqabot.config.settings.git_review_bot", "")
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    mocker.patch("openqabot.approver.get_json", return_value=[{"job_id": 100000, "status": "passed"}])
    mocker.patch("osc.core.change_review_state")
    mock_review_pr = mocker.patch("openqabot.approver.review_pr")

    assert Approver(args)() == 0
    expected = [
        "Submissions to approve:",
        "Submission approval process finished",
        "* SUSE:Maintenance:1:100",
        "Approving SUSE:Maintenance:1:100",
        "* SUSE:Maintenance:2:200",
        "Approving SUSE:Maintenance:2:200",
        "* SUSE:Maintenance:3:300",
        "Approving SUSE:Maintenance:3:300",
        "* SUSE:Maintenance:4:400",
        "Approving SUSE:Maintenance:4:400",
        "* git:5",
        "Approving git:5",
    ]
    assert_log_messages(caplog.messages, expected)
    mock_review_pr.assert_called_once_with(mocker.ANY, mocker.ANY, 5, mocker.ANY, mocker.ANY)
