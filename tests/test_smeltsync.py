# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import logging
import re
from collections import namedtuple

import pytest

import openqabot.smeltsync
import responses
from openqabot import QEM_DASHBOARD, SMELT
from openqabot.smeltsync import SMELTSync
from responses import matchers

# Fake Namespace for SyncRes initialization
_namespace = namedtuple("Namespace", ("dry", "token", "retry"))


@pytest.fixture(scope="function")
def fake_smelt_api(request):
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
                                                            }
                                                        },
                                                    ]
                                                },
                                            }
                                        }
                                    ]
                                },
                                "packages": {"edges": [{"node": {"name": "xrdp"}}]},
                                "crd": request.param[3],
                                "priority": request.param[4],
                            }
                        }
                    ]
                }
            }
        },
    )


@pytest.fixture(scope="function")
def fake_qem(monkeypatch):
    def f_active_inc(*_args):
        return ["100"]

    monkeypatch.setattr(openqabot.smeltsync, "get_active_incidents", f_active_inc)


@pytest.fixture(scope="function")
def fake_dashboard_replyback():
    def reply_callback(request):
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
def test_sync_qam_inreview(caplog):
    caplog.set_level(logging.DEBUG, logger="bot.syncres")
    assert SMELTSync(_namespace(False, "123", False))() == 0
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
def test_no_embragoed_and_priority_value(caplog):
    caplog.set_level(logging.DEBUG, logger="bot.syncres")
    assert SMELTSync(_namespace(False, "123", False))() == 0
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
def test_sync_approved(caplog):
    caplog.set_level(logging.DEBUG, logger="bot.syncres")
    assert SMELTSync(_namespace(False, "123", False))() == 0
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
