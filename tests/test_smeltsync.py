# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# ruff: noqa: S106 "Possible hardcoded password assigned to argument"

import logging
import re
from argparse import Namespace
from collections.abc import Generator
from typing import Any, cast
from unittest.mock import patch

import pytest

import responses
from openqabot.config import QEM_DASHBOARD, SMELT
from openqabot.smeltsync import SMELTSync
from responses import matchers


@pytest.fixture
def fake_smelt_api(request: pytest.FixtureRequest) -> None:
    responses.add(
        responses.GET,
        re.compile(SMELT + r"\?query=.*"),
        json={
            "data": {
                "incidents": {
                    "edges": [
                        {
                            "node": {
                                "emu": False,
                                "project": "SUSE:Maintenance:100",
                                "repositories": {"edges": [{"node": {"name": "SUSE:SLE-15:Update"}}]},
                                "requestSet": {
                                    "edges": [
                                        {
                                            "node": {
                                                "requestId": 1000,
                                                "status": {"name": request.param[2]},
                                                "reviewSet": {
                                                    "edges": [
                                                        {
                                                            "node": {
                                                                "assignedByGroup": {"name": request.param[0]},
                                                                "status": {"name": request.param[1]},
                                                            },
                                                        },
                                                    ],
                                                },
                                            },
                                        },
                                    ],
                                },
                                "packages": {"edges": [{"node": {"name": "xrdp"}}]},
                                "crd": request.param[3],
                                "priority": request.param[4],
                            },
                        },
                    ],
                },
            },
        },
    )


@pytest.fixture
def fake_qem() -> Generator[None, None, None]:
    def f_active_sub(*_args: Any) -> list[str]:
        return ["100"]

    with patch("openqabot.smeltsync.get_active_submission_ids", side_effect=f_active_sub):
        yield


@pytest.fixture
def fake_dashboard_replyback() -> None:
    def reply_callback(request: Any) -> tuple[int, dict[str, str], bytes]:
        return (200, {}, request.body)

    responses.add_callback(
        responses.PATCH,
        re.compile(f"{QEM_DASHBOARD}api/incidents"),
        callback=reply_callback,
        match=[matchers.query_param_matcher({})],
    )


@responses.activate
@pytest.mark.parametrize("fake_qem", [()], indirect=True)
@pytest.mark.parametrize(
    "fake_smelt_api",
    [["qam-openqa", "new", "review", "2023-01-01 04:31:12", 600]],
    indirect=True,
)
@pytest.mark.usefixtures("fake_qem", "fake_smelt_api", "fake_dashboard_replyback")
def test_sync_qam_inreview(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    assert SMELTSync(Namespace(dry=False, token="123", retry=False))() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Fetching details for SMELT incident smelt:100" in messages
    assert "Syncing SMELT incidents to QEM Dashboard" in messages
    assert "Updating 1 submissions on QEM Dashboard" in messages
    assert len(responses.calls) == 2
    assert len(cast("Any", responses.calls[1].response).json()) == 1
    submission = cast("Any", responses.calls[1].response).json()[0]
    assert submission["inReviewQAM"]
    assert submission["isActive"]
    assert not submission["approved"]
    assert submission["embargoed"]
    assert submission["priority"] == 600


@responses.activate
@pytest.mark.parametrize("fake_qem", [()], indirect=True)
@pytest.mark.parametrize("fake_smelt_api", [["qam-openqa", "new", "review", None, None]], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_smelt_api", "fake_dashboard_replyback")
def test_no_embragoed_and_priority_value(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.syncres")
    assert SMELTSync(Namespace(dry=False, token="123", retry=False))() == 0
    assert len(responses.calls) == 2
    assert len(cast("Any", responses.calls[1].response).json()) == 1
    submission = cast("Any", responses.calls[1].response).json()[0]
    assert not submission["embargoed"]
    assert submission["priority"] is None


@responses.activate
@pytest.mark.parametrize("fake_qem", [()], indirect=True)
@pytest.mark.parametrize(
    "fake_smelt_api",
    [["qam-openqa", "accepted", "new", "2023-01-01 04:31:12", 600]],
    indirect=True,
)
@pytest.mark.usefixtures("fake_qem", "fake_smelt_api", "fake_dashboard_replyback")
def test_sync_approved(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    assert SMELTSync(Namespace(dry=False, token="123", retry=False))() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Fetching details for SMELT incident smelt:100" in messages
    assert "Syncing SMELT incidents to QEM Dashboard" in messages
    assert "Updating 1 submissions on QEM Dashboard" in messages
    assert len(responses.calls) == 2
    assert len(cast("Any", responses.calls[1].response).json()) == 1
    assert not cast("Any", responses.calls[1].response).json()[0]["inReviewQAM"]
    assert not cast("Any", responses.calls[1].response).json()[0]["isActive"]
    assert cast("Any", responses.calls[1].response).json()[0]["approved"]
    assert cast("Any", responses.calls[1].response).json()[0]["embargoed"]


@responses.activate
@pytest.mark.parametrize("fake_qem", [()], indirect=True)
@pytest.mark.parametrize(
    "fake_smelt_api",
    [["qam-openqa", "new", "review", "2023-01-01 04:31:12", 600]],
    indirect=True,
)
@pytest.mark.usefixtures("fake_qem", "fake_smelt_api")
def test_sync_dry_run(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.smeltsync")
    assert SMELTSync(Namespace(dry=True, token="123", retry=False))() == 0
    assert "Dry run: Skipping dashboard update" in caplog.text


def test_review_rrequest_with_invalid_valid_and_empty_is_handled_gracefully() -> None:
    request_set = [{"requestId": 1, "status": {"name": "declined"}}]
    assert SMELTSync._review_rrequest(request_set) is None  # noqa: SLF001
    request_set = [{"requestId": 1, "status": {"name": "review"}}]
    assert SMELTSync._review_rrequest(request_set) is not None  # noqa: SLF001
    assert SMELTSync._review_rrequest([]) is None  # noqa: SLF001


def test_is_inreview() -> None:
    rr_number = {"status": {"name": "new"}, "reviewSet": [{"foo": "bar"}]}
    assert not SMELTSync._is_inreview(rr_number)  # noqa: SLF001
    rr_number = {"status": {"name": "review"}, "reviewSet": [{"foo": "bar"}]}
    assert SMELTSync._is_inreview(rr_number)  # noqa: SLF001
    rr_number = {"status": {"name": "new"}, "reviewSet": []}
    assert not SMELTSync._is_inreview(rr_number)  # noqa: SLF001


def test_is_revoked() -> None:
    rr_number = {"status": {"name": "new"}, "reviewSet": [{"foo": "bar"}]}
    assert not SMELTSync._is_revoked(rr_number)  # noqa: SLF001
    rr_number = {"status": {"name": "revoked"}, "reviewSet": [{"foo": "bar"}]}
    assert SMELTSync._is_revoked(rr_number)  # noqa: SLF001
    rr_number = {"status": {"name": "new"}, "reviewSet": []}
    assert not SMELTSync._is_revoked(rr_number)  # noqa: SLF001


def test_create_record_no_request_set() -> None:
    sub = {
        "project": "SUSE:Maintenance:123",
        "emu": False,
        "packages": [],
        "repositories": [],
        "crd": None,
        "priority": 0,
        "requestSet": [],
    }
    record = SMELTSync._create_record(sub)  # noqa: SLF001
    assert not record["inReview"]
    assert not record["approved"]
    assert not record["inReviewQAM"]
    assert record["rr_number"] is None


def test_is_revoked_true() -> None:
    rr_number = {"status": {"name": "revoked"}, "reviewSet": [{"foo": "bar"}]}
    assert SMELTSync._is_revoked(rr_number)  # noqa: SLF001


def test_has_qam_review_correct_status_passes() -> None:
    rr_number = {"reviewSet": [{"assignedByGroup": {"name": "qam-openqa"}, "status": {"name": "review"}}]}
    assert SMELTSync._has_qam_review(rr_number)  # noqa: SLF001


def test_has_qam_review_empty_set_fails() -> None:
    rr_number = {"reviewSet": []}
    assert not SMELTSync._has_qam_review(rr_number)  # noqa: SLF001
