# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# ruff: noqa: S106 "Possible hardcoded password assigned to argument"

import logging
import re
from collections.abc import Generator
from typing import Any, NamedTuple
from unittest.mock import patch

import pytest

import responses
from openqabot.config import QEM_DASHBOARD, SMELT
from openqabot.smeltsync import SMELTSync
from responses import matchers


# Fake Namespace for SyncRes initialization
class _namespace(NamedTuple):
    dry: bool
    token: str
    retry: bool


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
    def f_active_inc(*_args: Any) -> list[str]:
        return ["100"]

    with patch("openqabot.smeltsync.get_active_incidents", side_effect=f_active_inc):
        yield


@pytest.fixture
def fake_dashboard_replyback() -> None:
    def reply_callback(request: pytest.FixtureRequest) -> tuple[int, list[Any], bytes]:
        return (200, [], request.body)

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
    caplog.set_level(logging.DEBUG, logger="bot.syncres")
    assert SMELTSync(_namespace(dry=False, token="123", retry=False))() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Getting info about incident 100 from SMELT" in messages
    assert "Starting to sync incidents from smelt to dashboard" in messages
    assert "Updating info about 1 incidents" in messages
    assert len(responses.calls) == 2
    assert len(responses.calls[1].response.json()) == 1
    incident = responses.calls[1].response.json()[0]
    assert incident["inReviewQAM"]
    assert incident["isActive"]
    assert not incident["approved"]
    assert incident["embargoed"]
    assert incident["priority"] == 600


@responses.activate
@pytest.mark.parametrize("fake_qem", [()], indirect=True)
@pytest.mark.parametrize("fake_smelt_api", [["qam-openqa", "new", "review", None, None]], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_smelt_api", "fake_dashboard_replyback")
def test_no_embragoed_and_priority_value(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.syncres")
    assert SMELTSync(_namespace(dry=False, token="123", retry=False))() == 0
    assert len(responses.calls) == 2
    assert len(responses.calls[1].response.json()) == 1
    incident = responses.calls[1].response.json()[0]
    assert not incident["embargoed"]
    assert incident["priority"] is None


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
    caplog.set_level(logging.DEBUG, logger="bot.syncres")
    assert SMELTSync(_namespace(dry=False, token="123", retry=False))() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Getting info about incident 100 from SMELT" in messages
    assert "Starting to sync incidents from smelt to dashboard" in messages
    assert "Updating info about 1 incidents" in messages
    assert len(responses.calls) == 2
    assert len(responses.calls[1].response.json()) == 1
    assert not responses.calls[1].response.json()[0]["inReviewQAM"]
    assert not responses.calls[1].response.json()[0]["isActive"]
    assert responses.calls[1].response.json()[0]["approved"]
    assert responses.calls[1].response.json()[0]["embargoed"]


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
    assert SMELTSync(_namespace(dry=True, token="123", retry=False))() == 0
    assert "Dry run, nothing synced" in caplog.text


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
    inc = {
        "project": "SUSE:Maintenance:123",
        "emu": False,
        "packages": [],
        "repositories": [],
        "crd": None,
        "priority": 0,
        "requestSet": [],
    }
    record = SMELTSync._create_record(inc)  # noqa: SLF001
    assert not record["inReview"]
    assert not record["approved"]
    assert not record["inReviewQAM"]
    assert record["rr_number"] is None


def test_is_revoked_true() -> None:
    rr_number = {"status": {"name": "revoked"}, "reviewSet": [{"foo": "bar"}]}
    assert SMELTSync._is_revoked(rr_number)  # noqa: SLF001
