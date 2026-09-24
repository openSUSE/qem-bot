# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test approve OBS."""

import io
import logging
from typing import Any
from urllib.error import HTTPError

import pytest
import responses
from pytest_mock import MockerFixture

from openqabot.approver import Approver
from openqabot.config import settings
from openqabot.loader.qem import SubReq

from .helpers import (
    ReviewState,
    args,
    assert_log_messages,
)


@pytest.fixture(autouse=True)
def mock_request_from_api_default(mocker: MockerFixture) -> Any:
    req = mocker.Mock()
    req.reviews = [ReviewState("review", settings.obs_group)]
    return mocker.patch("osc.core.Request.from_api", return_value=req)


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


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs", "f_osconf")
def test_403_response(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    mocker.patch("openqabot.approver.approve_pr", return_value=True)
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch("osc.core.change_review_state", side_effect=ObsHTTPError(403, "Not allowed", "sd", None))
    assert Approver(args)() == 0
    assert "Received 'Not allowed'. Request 100 likely already approved, ignoring" in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs", "f_osconf")
def test_404_response(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    mocker.patch("openqabot.approver.approve_pr", return_value=True)
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
    mocker.patch("openqabot.approver.approve_pr", return_value=True)
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch("osc.core.change_review_state", side_effect=ObsHTTPError(500, "Not allowed", "sd", None))
    assert Approver(args)() == 1
    assert "OBS API error for request 400: 500 - Not allowed" in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs", "f_osconf")
def test_osc_unknown_exception(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    mocker.patch("openqabot.approver.approve_pr", return_value=True)
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch("osc.core.change_review_state", side_effect=ArbitraryObsError)
    assert Approver(args)() == 1
    assert "OBS API error: Failed to approve request" in caplog.text


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs", "f_osconf")
def test_osc_all_pass(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    mocker.patch("openqabot.approver.dashboard.get_json", return_value=[{"job_id": 100000, "status": "passed"}])
    mocker.patch("osc.core.change_review_state")
    mock_review_pr = mocker.patch("openqabot.approver.approve_pr", return_value=True)

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


@pytest.mark.parametrize(
    ("reviews", "expected_calls"),
    [
        ([ReviewState("review", settings.obs_group)], 1),
        (
            [
                ReviewState("review", settings.obs_group),
                ReviewState("review", settings.obs_group),
                ReviewState("new", settings.obs_group),
            ],
            3,
        ),
        ([], 1),
        (
            [
                ReviewState("review", settings.obs_group),
                ReviewState("review", "other-group"),
                ReviewState("accepted", settings.obs_group),
            ],
            1,
        ),
    ],
    ids=[
        "one_pending_review",
        "three_pending_reviews",
        "no_pending_reviews_fallback_to_1",
        "one_pending_matching_others_ignored",
    ],
)
def test_osc_approve_duplicate_reviews(mocker: MockerFixture, reviews: list[ReviewState], expected_calls: int) -> None:
    req = mocker.Mock()
    req.reviews = reviews
    mock_from_api = mocker.patch("osc.core.Request.from_api", return_value=req)
    mock_change_state = mocker.patch("osc.core.change_review_state")
    sub = SubReq(sub=123, req=100)

    res = Approver.osc_approve(sub, "testmsg")

    assert res is True
    mock_from_api.assert_called_once_with(settings.obs_url, 100)
    assert mock_change_state.call_count == expected_calls
    for call in mock_change_state.call_args_list:
        assert call.kwargs["reqid"] == "100"
        assert call.kwargs["newstate"] == "accepted"
        assert call.kwargs["by_group"] == settings.obs_group


def test_osc_approve_exception_fallback(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.requests")
    mock_from_api = mocker.patch("osc.core.Request.from_api", side_effect=Exception("API failure"))
    mock_change_state = mocker.patch("osc.core.change_review_state")
    sub = SubReq(sub=123, req=100)

    res = Approver.osc_approve(sub, "testmsg")

    assert res is True
    mock_from_api.assert_called_once_with(settings.obs_url, 100)
    mock_change_state.assert_called_once()
    assert "Failed to fetch request 100 from API to count pending reviews" in caplog.text
