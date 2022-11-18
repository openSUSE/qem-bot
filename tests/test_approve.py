from collections import namedtuple
import logging
import re
from urllib.error import HTTPError
from urllib.parse import urlparse

import functools
import osc.conf
import osc.core
import pytest
import responses
from typing import Dict, List

import openqabot.approver
from openqabot.approver import Approver
from openqabot.errors import NoResultsError
from openqabot.loader.qem import IncReq, JobAggr

# Fake Namespace for Approver initialization
_namespace = namedtuple(
    "Namespace", ("dry", "token", "all_incidents", "openqa_instance", "incident")
)
openqa_instance_url = urlparse("http://instance.qa")


@pytest.fixture(scope="function")
def fake_openqa_comment_api():
    responses.add(
        responses.GET,
        re.compile(r"http://instance.qa/api/v1/jobs/.*/comments"),
        json={"error": "job not found"},
        status=404,
    )


@pytest.fixture(scope="function")
def fake_responses_for_unblocking_incidents_via_openqa_comments(request):
    responses.add(
        responses.GET,
        "http://dashboard.qam.suse.de/api/jobs/update/20005",
        json=[{"status": "passed"}, {"status": "failed"}, {"status": "passed"}],
    )
    responses.add(
        responses.GET,
        re.compile(r"http://dashboard.qam.suse.de/api/jobs/.*/.*"),
        json=[{"status": "passed"}, {"status": "passed"}],
    )
    responses.add(
        responses.GET,
        url="http://instance.qa/api/v1/jobs/20005/comments",
        json=[{"text": "@review:acceptable_for:incident_%s:foo" % request.param}],
    )


@pytest.fixture(scope="function")
def fake_qem(monkeypatch, request):
    def f_inc_approver(*args):
        return [IncReq(1, 100), IncReq(2, 200), IncReq(3, 300), IncReq(4, 400)]

    def f_inc_single_approver(token: Dict[str, str], id: int) -> List[IncReq]:
        return [IncReq(1, 100) if id == 1 else IncReq(4, 400)]

    # inc 1 needs aggregates
    # inc 2 needs aggregates
    # Inc 3 part needs aggregates
    # Inc 4 dont need aggregates

    def f_inc_settins(inc, token, all_inc):
        if "inc" in request.param:
            raise NoResultsError("No results for settings")
        results = {
            1: [JobAggr(i, False, True) for i in range(1000, 1010)],
            2: [JobAggr(i, False, True) for i in range(2000, 2010)],
            3: [
                JobAggr(3000, False, False),
                JobAggr(3001, False, False),
                JobAggr(3002, False, True),
                JobAggr(3002, False, False),
                JobAggr(3003, False, True),
            ],
            4: [JobAggr(i, False, False) for i in range(4000, 4010)],
        }
        return results.get(inc, None)

    def f_aggr_settings(inc, token):
        if "aggr" in request.param:
            raise NoResultsError("No results for settings")
        results = {
            4: [],
            1: [JobAggr(i, True, False) for i in range(10000, 10010)],
            2: [JobAggr(i, True, False) for i in range(20000, 20010)],
            3: [JobAggr(i, True, False) for i in range(30000, 30010)],
        }
        return results.get(inc, None)

    monkeypatch.setattr(
        openqabot.approver, "get_single_incident", f_inc_single_approver
    )
    monkeypatch.setattr(openqabot.approver, "get_incidents_approver", f_inc_approver)
    monkeypatch.setattr(openqabot.approver, "get_incident_settings", f_inc_settins)
    monkeypatch.setattr(openqabot.approver, "get_aggregate_settings", f_aggr_settings)


@pytest.fixture
def f_osconf(monkeypatch):
    def fake(*args, **kwds):
        pass

    monkeypatch.setattr(osc.conf, "get_config", fake)


@responses.activate
@pytest.mark.xfail(reason="Bug in responses")
@pytest.mark.parametrize("fake_qem", [("NoResultsError isn't raised")], indirect=True)
def test_no_jobs(fake_qem, caplog):
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    responses.add(
        responses.GET,
        re.compile(r"http://dashboard.qam.suse.de/api/jobs/.*/.*"),
        json={},
    )
    args = _namespace(True, "123", False, openqa_instance_url, None)

    approver = Approver(args)
    approver()

    assert len(caplog.records) == 42
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Inc 4 has at least one failed job in incident tests" in messages
    assert "Incidents to approve:" in messages
    assert "End of bot run" in messages
    assert "SUSE:Maintenance:4:400" not in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", [("NoResultsError isn't raised")], indirect=True)
def test_single_incident(fake_qem, caplog):
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    responses.add(
        responses.GET,
        re.compile(r"http://dashboard.qam.suse.de/api/incident/.*"),
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
        re.compile(r"http://dashboard.qam.suse.de/api/jobs/incident/100"),
        json=[{"incident_settings": 1000, "job_id": 1, "status": "failed"}],
    )
    responses.add(
        responses.GET,
        re.compile(r"http://dashboard.qam.suse.de/api/jobs/incident/400"),
        json=[{"incident_settings": 1000, "job_id": 1, "status": "passed"}],
    )
    responses.add(
        responses.GET,
        re.compile(r"http://instance.qa/api/v1/jobs/.*/comments"),
        json=[],
    )
    responses.add(
        responses.GET,
        re.compile(r"http://dashboard.qam.suse.de/api/jobs/update/1000.*"),
        json=[{"status": "passed"}, {"status": "failed"}, {"status": "failed"}],
    )
    args = _namespace(True, "123", False, openqa_instance_url, 1)

    approver = Approver(args)
    approver()
    assert len(caplog.records) == 5
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Inc 1 has at least one failed job in incident tests" in messages
    assert "Incidents to approve:" in messages
    assert "End of bot run" in messages
    assert "SUSE:Maintenance:1:100" not in messages

    caplog.clear()

    args = _namespace(True, "123", False, openqa_instance_url, 4)
    approver = Approver(args)
    approver()
    assert len(caplog.records) == 4
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Inc 4 has at least one failed job in incident tests" not in messages
    assert "Incidents to approve:" in messages
    assert "End of bot run" in messages
    assert "SUSE:Maintenance:4:400" in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", [("NoResultsError isn't raised")], indirect=True)
def test_all_passed(fake_qem, caplog):
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    responses.add(
        responses.GET,
        re.compile(r"http://dashboard.qam.suse.de/api/jobs/.*/.*"),
        json=[{"status": "passed"}, {"status": "passed"}],
    )
    args = _namespace(True, "123", False, openqa_instance_url, None)

    approver = Approver(args)

    assert approver() == 0

    assert len(caplog.records) == 7
    messages = [x[-1] for x in caplog.record_tuples]
    assert "SUSE:Maintenance:1:100" in messages
    assert "SUSE:Maintenance:2:200" in messages
    assert "SUSE:Maintenance:3:300" in messages
    assert "SUSE:Maintenance:4:400" in messages
    assert "Incidents to approve:" in messages
    assert "End of bot run" in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", [("aggr")], indirect=True)
def test_inc_passed_aggr_without_results(fake_qem, caplog):
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    responses.add(
        responses.GET,
        re.compile(r"http://dashboard.qam.suse.de/api/jobs/.*/.*"),
        json=[{"status": "passed"}, {"status": "passed"}],
    )
    args = _namespace(True, "123", False, openqa_instance_url, None)

    approver = Approver(args)

    assert approver() == 0
    assert len(caplog.records) == 11
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Start approving incidents in IBS" in messages
    assert "Aggregate missing for 1" in messages
    assert "Aggregate missing for 2" in messages
    assert "Aggregate missing for 3" in messages
    assert "Incidents to approve:" in messages
    assert "SUSE:Maintenance:4:400" in messages
    assert "End of bot run" in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", [("inc")], indirect=True)
def test_inc_without_results(fake_qem, caplog):
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    responses.add(
        responses.GET,
        re.compile(r"http://dashboard.qam.suse.de/api/jobs/.*/.*"),
        json=[{"status": "passed"}, {"status": "passed"}],
    )
    args = _namespace(True, "123", False, openqa_instance_url, None)

    approver = Approver(args)

    assert approver() == 0
    assert len(caplog.records) == 7
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Start approving incidents in IBS" in messages
    assert "Incidents to approve:" in messages
    assert "SUSE:Maintenance" not in messages
    assert "End of bot run" in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", [("NoResultsError isn't raised")], indirect=True)
def test_403_response(fake_qem, f_osconf, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def f_osc_core(*args, **kwds):
        raise HTTPError("Fake OBS", 403, "Not allowed", "sd", None)

    monkeypatch.setattr(osc.core, "change_review_state", f_osc_core)

    responses.add(
        responses.GET,
        re.compile(r"http://dashboard.qam.suse.de/api/jobs/.*/.*"),
        json=[{"status": "passed"}, {"status": "passed"}],
    )
    args = _namespace(False, "123", False, openqa_instance_url, None)

    approver = Approver(args)
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert messages == [
        "Start approving incidents in IBS",
        "Incidents to approve:",
        "SUSE:Maintenance:1:100",
        "SUSE:Maintenance:2:200",
        "SUSE:Maintenance:3:300",
        "SUSE:Maintenance:4:400",
        "Accepting review for SUSE:Maintenance:1:100",
        "Received 'Not allowed'. Request 100 likely already approved, ignoring",
        "Accepting review for SUSE:Maintenance:2:200",
        "Received 'Not allowed'. Request 200 likely already approved, ignoring",
        "Accepting review for SUSE:Maintenance:3:300",
        "Received 'Not allowed'. Request 300 likely already approved, ignoring",
        "Accepting review for SUSE:Maintenance:4:400",
        "Received 'Not allowed'. Request 400 likely already approved, ignoring",
        "End of bot run",
    ]


@responses.activate
@pytest.mark.parametrize("fake_qem", [("NoResultsError isn't raised")], indirect=True)
def test_404_response(fake_qem, f_osconf, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def f_osc_core(*args, **kwds):
        raise HTTPError("Fake OBS", 404, "Not allowed", "sd", None)

    monkeypatch.setattr(osc.core, "change_review_state", f_osc_core)

    responses.add(
        responses.GET,
        re.compile(r"http://dashboard.qam.suse.de/api/jobs/.*/.*"),
        json=[{"status": "passed"}, {"status": "passed"}],
    )
    args = _namespace(False, "123", False, openqa_instance_url, None)

    approver = Approver(args)
    assert approver() == 1
    messages = [x[-1] for x in caplog.record_tuples]
    assert messages == [
        "Start approving incidents in IBS",
        "Incidents to approve:",
        "SUSE:Maintenance:1:100",
        "SUSE:Maintenance:2:200",
        "SUSE:Maintenance:3:300",
        "SUSE:Maintenance:4:400",
        "Accepting review for SUSE:Maintenance:1:100",
        "Received 'Not allowed'. Request 100 removed or problem on OBS side, ignoring",
        "Accepting review for SUSE:Maintenance:2:200",
        "Received 'Not allowed'. Request 200 removed or problem on OBS side, ignoring",
        "Accepting review for SUSE:Maintenance:3:300",
        "Received 'Not allowed'. Request 300 removed or problem on OBS side, ignoring",
        "Accepting review for SUSE:Maintenance:4:400",
        "Received 'Not allowed'. Request 400 removed or problem on OBS side, ignoring",
        "End of bot run",
    ]


@responses.activate
@pytest.mark.parametrize("fake_qem", [("NoResultsError isn't raised")], indirect=True)
def test_500_response(fake_qem, f_osconf, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def f_osc_core(*args, **kwds):
        raise HTTPError("Fake OBS", 500, "Not allowed", "sd", None)

    monkeypatch.setattr(osc.core, "change_review_state", f_osc_core)

    responses.add(
        responses.GET,
        re.compile(r"http://dashboard.qam.suse.de/api/jobs/.*/.*"),
        json=[{"status": "passed"}, {"status": "passed"}],
    )
    args = _namespace(False, "123", False, openqa_instance_url, None)

    approver = Approver(args)
    assert approver() == 1
    messages = [x[-1] for x in caplog.record_tuples]
    assert messages == [
        "Start approving incidents in IBS",
        "Incidents to approve:",
        "SUSE:Maintenance:1:100",
        "SUSE:Maintenance:2:200",
        "SUSE:Maintenance:3:300",
        "SUSE:Maintenance:4:400",
        "Accepting review for SUSE:Maintenance:1:100",
        "Recived error 500, reason: 'Not allowed' for Request 100 - problem on OBS side",
        "Accepting review for SUSE:Maintenance:2:200",
        "Recived error 500, reason: 'Not allowed' for Request 200 - problem on OBS side",
        "Accepting review for SUSE:Maintenance:3:300",
        "Recived error 500, reason: 'Not allowed' for Request 300 - problem on OBS side",
        "Accepting review for SUSE:Maintenance:4:400",
        "Recived error 500, reason: 'Not allowed' for Request 400 - problem on OBS side",
        "End of bot run",
    ]


@responses.activate
@pytest.mark.parametrize("fake_qem", [("NoResultsError isn't raised")], indirect=True)
def test_osc_unknown_exception(fake_qem, f_osconf, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def f_osc_core(*args, **kwds):
        raise Exception("Fake OBS exception")

    monkeypatch.setattr(osc.core, "change_review_state", f_osc_core)

    responses.add(
        responses.GET,
        re.compile(r"http://dashboard.qam.suse.de/api/jobs/.*/.*"),
        json=[{"status": "passed"}, {"status": "passed"}],
    )
    args = _namespace(False, "123", False, openqa_instance_url, None)

    approver = Approver(args)
    assert approver() == 1
    messages = [x[-1] for x in caplog.record_tuples]
    assert messages == [
        "Start approving incidents in IBS",
        "Incidents to approve:",
        "SUSE:Maintenance:1:100",
        "SUSE:Maintenance:2:200",
        "SUSE:Maintenance:3:300",
        "SUSE:Maintenance:4:400",
        "Accepting review for SUSE:Maintenance:1:100",
        "Fake OBS exception",
        "Accepting review for SUSE:Maintenance:2:200",
        "Fake OBS exception",
        "Accepting review for SUSE:Maintenance:3:300",
        "Fake OBS exception",
        "Accepting review for SUSE:Maintenance:4:400",
        "Fake OBS exception",
        "End of bot run",
    ]


@responses.activate
@pytest.mark.parametrize("fake_qem", [("NoResultsError isn't raised")], indirect=True)
def test_osc_all_pass(fake_qem, f_osconf, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def f_osc_core(*args, **kwds):
        pass

    monkeypatch.setattr(osc.core, "change_review_state", f_osc_core)

    responses.add(
        responses.GET,
        re.compile(r"http://dashboard.qam.suse.de/api/jobs/.*/.*"),
        json=[{"status": "passed"}, {"status": "passed"}],
    )
    args = _namespace(False, "123", False, openqa_instance_url, None)

    approver = Approver(args)
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert messages == [
        "Start approving incidents in IBS",
        "Incidents to approve:",
        "SUSE:Maintenance:1:100",
        "SUSE:Maintenance:2:200",
        "SUSE:Maintenance:3:300",
        "SUSE:Maintenance:4:400",
        "Accepting review for SUSE:Maintenance:1:100",
        "Accepting review for SUSE:Maintenance:2:200",
        "Accepting review for SUSE:Maintenance:3:300",
        "Accepting review for SUSE:Maintenance:4:400",
        "End of bot run",
    ]


@responses.activate
@pytest.mark.parametrize("fake_qem", [("NoResultsError isn't raised")], indirect=True)
def test_one_incident_failed(fake_qem, fake_openqa_comment_api, caplog):
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    responses.add(
        responses.GET,
        "http://dashboard.qam.suse.de/api/jobs/incident/1005",
        json=[{"status": "passed"}, {"status": "failed"}, {"status": "passed"}],
    )

    responses.add(
        responses.GET,
        re.compile(r"http://dashboard.qam.suse.de/api/jobs/.*/.*"),
        json=[{"status": "passed"}, {"status": "passed"}],
    )
    args = _namespace(True, "123", False, openqa_instance_url, None)

    approver = Approver(args)
    approver.client.retries = 0

    assert approver() == 0

    assert len(caplog.records) == 8
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Inc 1 has at least one failed job in incident tests" in messages
    assert "SUSE:Maintenance:2:200" in messages
    assert "SUSE:Maintenance:3:300" in messages
    assert "SUSE:Maintenance:4:400" in messages
    assert "Incidents to approve:" in messages
    assert "End of bot run" in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", [("NoResultsError isn't raised")], indirect=True)
def test_one_aggr_failed(fake_qem, fake_openqa_comment_api, caplog):
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    responses.add(
        responses.GET,
        "http://dashboard.qam.suse.de/api/jobs/update/20005",
        json=[{"status": "passed"}, {"status": "failed"}, {"status": "passed"}],
    )

    responses.add(
        responses.GET,
        re.compile(r"http://dashboard.qam.suse.de/api/jobs/.*/.*"),
        json=[{"status": "passed"}, {"status": "passed"}],
    )
    args = _namespace(True, "123", False, openqa_instance_url, None)

    approver = Approver(args)
    approver.client.retries = 0

    assert approver() == 0

    assert len(caplog.records) == 8
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Inc 2 has at least one failed job in aggregate tests" in messages
    assert "SUSE:Maintenance:1:100" in messages
    assert "SUSE:Maintenance:3:300" in messages
    assert "SUSE:Maintenance:4:400" in messages
    assert "Incidents to approve:" in messages
    assert "End of bot run" in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", [("NoResultsError isn't raised")], indirect=True)
@pytest.mark.parametrize(
    "fake_responses_for_unblocking_incidents_via_openqa_comments", [(2)], indirect=True
)
def test_approval_unblocked_via_openqa_comment(
    fake_qem,
    fake_responses_for_unblocking_incidents_via_openqa_comments,
    fake_openqa_comment_api,
    caplog,
):
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    approver = Approver(_namespace(True, "123", False, openqa_instance_url, None))
    approver.client.retries = 0
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "SUSE:Maintenance:2:200" in messages
    assert "Ignoring failed job 20005 for incident 2 due to openQA comment" in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", [("NoResultsError isn't raised")], indirect=True)
@pytest.mark.parametrize(
    "fake_responses_for_unblocking_incidents_via_openqa_comments", [(22)], indirect=True
)
def test_approval_still_blocked_if_openqa_comment_not_relevant(
    fake_qem,
    fake_responses_for_unblocking_incidents_via_openqa_comments,
    fake_openqa_comment_api,
    caplog,
):
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    approver = Approver(_namespace(True, "123", False, openqa_instance_url, None))
    approver.client.retries = 0
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "SUSE:Maintenance:2:200" not in messages
