from collections import namedtuple
import logging
import re

import functools
import pytest
import responses

import openqabot.smeltsync
from openqabot.smeltsync import SMELTSync

# Fake Namespace for SyncRes initialization
_namespace = namedtuple("Namespace", ("dry", "token", "retry"))


@pytest.fixture(scope="function")
def fake_smelt_api(request):
    responses.add(
        responses.GET,
        re.compile(r"https://smelt.suse.de/graphql\?query=.*"),
        json={
            "data": {
                "incidents": {
                    "edges": [
                        {
                            "node": {
                                "emu": False,
                                "project": "SUSE:Maintenance:100",
                                "repositories": {
                                    "edges": [{"node": {"name": "SUSE:SLE-15:Update"}}]
                                },
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
                                                                "assignedByGroup": {
                                                                    "name": request.param[
                                                                        0
                                                                    ]
                                                                },
                                                                "status": {
                                                                    "name": request.param[
                                                                        1
                                                                    ]
                                                                },
                                                            }
                                                        },
                                                    ]
                                                },
                                            }
                                        }
                                    ]
                                },
                                "packages": {"edges": [{"node": {"name": "xrdp"}}]},
                            }
                        }
                    ]
                }
            }
        },
    )


@pytest.fixture(scope="function")
def fake_qem(monkeypatch, request):
    def f_active_inc(*args):
        return ["100"]

    monkeypatch.setattr(openqabot.smeltsync, "get_active_incidents", f_active_inc)


@pytest.fixture(scope="function")
def fake_dashboard_replyback():
    def reply_callback(request):
        return (200, [], request.body)

    responses.add_callback(
        responses.PATCH,
        re.compile(r"http://dashboard.qam.suse.de/api/incidents"),
        callback=reply_callback,
    )


@responses.activate
@pytest.mark.parametrize("fake_qem", [()], indirect=True)
@pytest.mark.parametrize(
    "fake_smelt_api", [(["qam-openqa", "new", "review"])], indirect=True
)
def test_sync_qam_inreview(fake_qem, caplog, fake_smelt_api, fake_dashboard_replyback):
    caplog.set_level(logging.DEBUG, logger="bot.syncres")
    assert SMELTSync(_namespace(False, "123", False))() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Getting info about incident 100 from SMELT" in messages
    assert "Start syncing incidents from smelt to dashboard" in messages
    assert "Updating info about 1 incidents" in messages
    assert len(responses.calls) == 2
    assert len(responses.calls[1].response.json()) == 1
    assert responses.calls[1].response.json()[0]["inReviewQAM"] == True
    assert responses.calls[1].response.json()[0]["isActive"] == True
    assert responses.calls[1].response.json()[0]["approved"] == False


@responses.activate
@pytest.mark.parametrize("fake_qem", [()], indirect=True)
@pytest.mark.parametrize(
    "fake_smelt_api", [(["qam-openqa", "accepted", "new"])], indirect=True
)
def test_sync_approved(fake_qem, caplog, fake_smelt_api, fake_dashboard_replyback):
    caplog.set_level(logging.DEBUG, logger="bot.syncres")
    assert SMELTSync(_namespace(False, "123", False))() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Getting info about incident 100 from SMELT" in messages
    assert "Start syncing incidents from smelt to dashboard" in messages
    assert "Updating info about 1 incidents" in messages
    assert len(responses.calls) == 2
    assert len(responses.calls[1].response.json()) == 1
    assert responses.calls[1].response.json()[0]["inReviewQAM"] == False
    assert responses.calls[1].response.json()[0]["isActive"] == False
    assert responses.calls[1].response.json()[0]["approved"] == True
