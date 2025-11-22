# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# ruff: noqa: S106 "Possible hardcoded password assigned to argument"

import io
import logging
import re
from typing import Any, NamedTuple, NoReturn
from urllib.error import HTTPError
from urllib.parse import urlparse

import osc.conf
import osc.core
import pytest

import openqabot.approver
import responses
from openqabot.approver import QEM_DASHBOARD, Approver
from openqabot.errors import NoResultsError
from openqabot.loader.qem import IncReq, JobAggr
from responses import matchers


# Fake Namespace for Approver initialization
class Namespace(NamedTuple):
    dry: bool
    token: str
    all_incidents: bool
    openqa_instance: str
    incident: str
    gitea_token: str


openqa_instance_url = urlparse("http://instance.qa")
args = Namespace(
    dry=False,
    token="123",
    all_incidents=False,
    openqa_instance=openqa_instance_url,
    incident=None,
    gitea_token=None,
)


@pytest.fixture
def fake_responses_for_unblocking_incidents_via_older_ok_result(
    request: pytest.FixtureRequest,
) -> None:
    responses.add(
        responses.GET,
        f"{QEM_DASHBOARD}api/jobs/update/20005",
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
        json=[{"text": "@review:acceptable_for:incident_555:foo"}],
    )
    responses.add(
        responses.GET,
        re.compile(r"http://instance.qa/tests/.*/ajax\?previous_limit=.*&next_limit=0"),
        json={
            "data": [
                {"build": "20240115-1", "id": 100002, "result": "failed"},
                {"build": "20240114-1", "id": 100004, "result": "failed"},
                {"build": "20240113-1", "id": 100005, "result": "softfailed"},
            ],
        },
    )
    responses.add(
        responses.GET,
        re.compile(r"http://instance.qa/api/v1/jobs/.*"),
        json={
            "job": {
                "settings": {
                    "BASE_TEST_REPOS": "http://download.suse.de/ibs/SUSE:/Maintenance:/1111/SUSE_Updates_SLE-Module-Basesystem_15-SP5_x86_64/,http://download.suse.de/ibs/SUSE:/Maintenance:/{}/SUSE_Updates_SLE-Module-Basesystem_15-SP5_x86_64/".format(
                        request.param
                    ),
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
def fake_dashboard_remarks_api() -> list[responses.BaseResponse]:
    return [
        responses.patch(
            f"{QEM_DASHBOARD}api/jobs/{job_id}/remarks?text=acceptable_for&incident_number=2",
            json=[{}],
        )
        for job_id in [100001, 100002, 100003, 100004]
    ]


def add_two_passed_response() -> None:
    responses.add(
        responses.GET,
        re.compile(f"{QEM_DASHBOARD}api/jobs/.*/.*"),
        json=[{"status": "passed"}, {"status": "passed"}],
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
def fake_two_passed_jobs() -> None:
    add_two_passed_response()


@pytest.fixture
def fake_responses_for_unblocking_incidents_via_openqa_comments(
    request: pytest.FixtureRequest,
) -> None:
    params = request.param
    incident = params["incident"]
    responses.add(
        responses.GET,
        f"{QEM_DASHBOARD}api/jobs/update/20005",
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
            json=[{"text": f"@review:acceptable_for:incident_{incident}:foo"}],
        )


@pytest.fixture
def fake_responses_updating_job() -> None:
    responses.add(responses.PATCH, f"{QEM_DASHBOARD}api/jobs/100001")


@pytest.fixture
def fake_responses_for_creating_pr_review() -> None:
    responses.add(
        responses.POST,
        "https://src.suse.de/api/v1/repos/products/SLFO/pulls/5/reviews",
        json={},
        match=[
            matchers.json_params_matcher(
                {
                    "body": f"Request accepted for 'qam-openqa' based on data in {QEM_DASHBOARD}",
                    "commit_id": "18bfa2a23fb7985d5d0cc356474a96a19d91d2d8652442badf7f13bc07cd1f3d",
                    "comments": [],
                    "event": "APPROVED",
                },
            ),
        ],
    )


@pytest.fixture
def fake_qem(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    def f_inc_approver(*_args: Any) -> list[IncReq]:
        return [
            IncReq(1, 100),
            IncReq(2, 200),
            IncReq(3, 300),
            IncReq(4, 400),
            IncReq(
                5,
                500,
                "git",
                "https://src.suse.de/products/SLFO/pulls/124",
                "18bfa2a23fb7985d5d0cc356474a96a19d91d2d8652442badf7f13bc07cd1f3d",
            ),
        ]

    def f_inc_single_approver(_token: dict[str, str], i: int) -> list[IncReq]:
        return [f_inc_approver()[i - 1]]

    # Inc 1 needs aggregates
    # Inc 2 needs aggregates
    # Inc 3 part needs aggregates
    # Inc 4 dont need aggregates

    class NoSettingsResultsError(NoResultsError):
        def __init__(self) -> None:
            super().__init__("No results for settings")

    def f_inc_settins(inc: int, _token: str, **_kwargs: Any) -> list[JobAggr]:
        if "inc" in request.param:
            raise NoSettingsResultsError
        results = {
            1: [JobAggr(i, aggregate=False, with_aggregate=True) for i in range(1000, 1010)],
            2: [JobAggr(i, aggregate=False, with_aggregate=True) for i in range(2000, 2010)],
            3: [
                JobAggr(3000, aggregate=False, with_aggregate=False),
                JobAggr(3001, aggregate=False, with_aggregate=False),
                JobAggr(3002, aggregate=False, with_aggregate=True),
                JobAggr(3002, aggregate=False, with_aggregate=False),
                JobAggr(3003, aggregate=False, with_aggregate=True),
            ],
            4: [JobAggr(i, aggregate=False, with_aggregate=False) for i in range(4000, 4010)],
            5: [JobAggr(i, aggregate=False, with_aggregate=False) for i in range(5000, 5010)],
        }
        return results.get(inc)

    def f_aggr_settings(inc: int, _token: str) -> list[JobAggr]:
        if "aggr" in request.param:
            raise NoSettingsResultsError
        results = {
            5: [],
            4: [],
            1: [JobAggr(i, aggregate=True, with_aggregate=False) for i in range(10000, 10010)],
            2: [JobAggr(i, aggregate=True, with_aggregate=False) for i in range(20000, 20010)],
            3: [JobAggr(i, aggregate=True, with_aggregate=False) for i in range(30000, 30010)],
        }
        return results.get(inc)

    monkeypatch.setattr(openqabot.approver, "get_single_incident", f_inc_single_approver)
    monkeypatch.setattr(openqabot.approver, "get_incidents_approver", f_inc_approver)
    monkeypatch.setattr(openqabot.approver, "get_incident_settings", f_inc_settins)
    monkeypatch.setattr(openqabot.approver, "get_aggregate_settings", f_aggr_settings)


@pytest.fixture
def f_osconf(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(*_args: Any, **_kwds: Any) -> None:
        pass

    monkeypatch.setattr(osc.conf, "get_config", fake)


def approver(incident: int = 0) -> int:
    args = Namespace(
        dry=True,
        token="123",
        all_incidents=False,
        openqa_instance=openqa_instance_url,
        incident=incident,
        gitea_token=None,
    )
    approver = Approver(args)
    approver.client.retries = 0
    return approver()


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures("fake_qem")
def test_no_jobs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    responses.add(responses.GET, re.compile(f"{QEM_DASHBOARD}api/jobs/.*/.*"), json={})
    approver()
    messages = [x[-1] for x in caplog.record_tuples]
    assert "SUSE:Maintenance:4:400 has at least one failed job in incident tests" in messages
    assert "Incidents to approve:" in messages
    assert "End of bot run" in messages
    assert "* SUSE:Maintenance:4:400" not in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures("fake_qem")
def test_single_incident(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    responses.add(
        responses.GET,
        re.compile(f"{QEM_DASHBOARD}api/incident/.*"),
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
        re.compile(f"{QEM_DASHBOARD}api/jobs/incident/100"),
        json=[{"incident_settings": 1000, "job_id": 100001, "status": "failed"}],
    )
    responses.add(
        responses.GET,
        re.compile(f"{QEM_DASHBOARD}api/jobs/incident/400"),
        json=[{"incident_settings": 1000, "job_id": 100000, "status": "passed"}],
    )
    responses.add(
        responses.GET,
        re.compile(r"http://instance.qa/api/v1/jobs/.*/comments"),
        json=[],
    )
    responses.add(
        responses.GET,
        re.compile(f"{QEM_DASHBOARD}api/jobs/update/1000.*"),
        json=[
            {"job_id": 100000, "status": "passed"},
            {"job_id": 100001, "status": "failed"},
            {"job_id": 100002, "status": "failed"},
        ],
    )
    approver(incident=1)
    assert len(caplog.records) >= 1, "we rely on log messages"
    messages = [x[-1] for x in caplog.record_tuples]
    assert "SUSE:Maintenance:1:100 has at least one failed job in incident tests" in messages
    assert "Found failed, not-ignored job http://instance.qa/t100001 for incident 1" in messages
    assert "Incidents to approve:" in messages
    assert "End of bot run" in messages
    assert "* SUSE:Maintenance:1:100" not in messages

    caplog.clear()
    approver(incident=4)
    assert len(caplog.records) >= 1, "we rely on log messages in tests"
    messages = [x[-1] for x in caplog.record_tuples]
    assert "SUSE:Maintenance:4:400 has at least one failed job in incident tests" not in messages
    assert "Incidents to approve:" in messages
    assert "End of bot run" in messages
    assert "* SUSE:Maintenance:4:400" in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_two_passed_jobs")
def test_all_passed(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    assert approver() == 0
    assert len(caplog.records) >= 1, "we rely on log messages in tests"
    messages = [x[-1] for x in caplog.record_tuples]
    assert "* SUSE:Maintenance:1:100" in messages
    assert "* SUSE:Maintenance:2:200" in messages
    assert "* SUSE:Maintenance:3:300" in messages
    assert "* SUSE:Maintenance:4:400" in messages
    assert "Incidents to approve:" in messages
    assert "End of bot run" in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", ["aggr"], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_two_passed_jobs")
def test_inc_passed_aggr_without_results(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    assert approver() == 0
    assert len(caplog.records) >= 1, "we rely on log messages in tests"
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Approving incidents in IBS or Gitea…" in messages
    assert "No aggregate test results found for SUSE:Maintenance:1:100" in messages
    assert "No aggregate test results found for SUSE:Maintenance:2:200" in messages
    assert "No aggregate test results found for SUSE:Maintenance:3:300" in messages
    assert "Incidents to approve:" in messages
    assert "* SUSE:Maintenance:4:400" in messages
    assert "End of bot run" in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", ["inc"], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_two_passed_jobs")
def test_inc_without_results(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    assert approver() == 0
    assert len(caplog.records) >= 1, "we rely on log messages in tests"
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Approving incidents in IBS or Gitea…" in messages
    assert "Incidents to approve:" in messages
    assert "* SUSE:Maintenance" not in messages
    assert "End of bot run" in messages


class ObsHTTPError(HTTPError):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__("Fake OBS", *args, **kwargs)


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_two_passed_jobs", "fake_responses_for_creating_pr_review", "f_osconf")
def test_403_response(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def f_osc_core(*_args: Any, **_kwds: Any) -> NoReturn:
        raise ObsHTTPError(403, "Not allowed", "sd", None)

    monkeypatch.setattr(osc.core, "change_review_state", f_osc_core)
    monkeypatch.setattr(openqabot.loader.gitea, "GIT_REVIEW_BOT", "")
    assert Approver(args)() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Received 'Not allowed'. Request 100 likely already approved, ignoring" in messages, (
        "Expected handling of 403 responses logged"
    )


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_two_passed_jobs", "f_osconf")
def test_404_response(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def f_osc_core(*_args: Any, **_kwds: Any) -> NoReturn:
        raise ObsHTTPError(404, "Not Found", None, io.BytesIO(b"review state"))

    monkeypatch.setattr(osc.core, "change_review_state", f_osc_core)
    assert Approver(args)() == 1
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Received 'Not Found'. Request 100 removed or problem on OBS side: review state" in messages, (
        "Expected handling of 404 responses logged"
    )


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_two_passed_jobs", "f_osconf")
def test_500_response(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def f_osc_core(*_args: Any, **_kwds: Any) -> NoReturn:
        class ObsHTTPError(HTTPError):
            def __init__(self) -> None:
                super().__init__("Fake OBS", 500, "Not allowed", "sd", None)

        raise ObsHTTPError

    monkeypatch.setattr(osc.core, "change_review_state", f_osc_core)
    assert Approver(args)() == 1
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Received error 500, reason: 'Not allowed' for Request 400 - problem on OBS side" in messages, (
        "Expected handling of 500 responses logged"
    )


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_two_passed_jobs", "f_osconf")
def test_osc_unknown_exception(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def f_osc_core(*_args: Any, **_kwds: Any) -> NoReturn:
        class ArbitraryObsError(Exception):
            def __init__(self) -> None:
                super().__init__("Fake OBS exception")

        raise ArbitraryObsError

    monkeypatch.setattr(osc.core, "change_review_state", f_osc_core)
    assert Approver(args)() == 1
    assert "Fake OBS exception" in caplog.text


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_two_passed_jobs", "fake_responses_for_creating_pr_review", "f_osconf")
def test_osc_all_pass(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def f_osc_core(*_args: Any, **_kwds: Any) -> None:
        pass

    monkeypatch.setattr(osc.core, "change_review_state", f_osc_core)
    monkeypatch.setattr(openqabot.loader.gitea, "GIT_REVIEW_BOT", "")
    assert Approver(args)() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Incidents to approve:" in messages, "start of run must be marked explicitly"
    assert "End of bot run" in messages, "end of run must be marked explicitly"
    for i in [
        "* SUSE:Maintenance:1:100",
        "* SUSE:Maintenance:2:200",
        "* SUSE:Maintenance:3:300",
        "* SUSE:Maintenance:4:400",
        "* git:5",
        "Accepting review for SUSE:Maintenance:1:100",
        "Accepting review for SUSE:Maintenance:2:200",
        "Accepting review for SUSE:Maintenance:3:300",
        "Accepting review for SUSE:Maintenance:4:400",
        "Accepting review for git:5",
    ]:
        assert i in messages, "individual reviews must be mentioned in logs"
    assert len(responses.calls) == 76


@pytest.fixture
def fake_incident_1_failed_2_passed(request: pytest.FixtureRequest) -> None:
    responses.add(
        responses.GET,
        f"{QEM_DASHBOARD}api/jobs/incident/%s" % request.param,
        json=[
            {"job_id": 100000, "status": "passed"},
            {"job_id": 100001, "status": "failed"},
            {"job_id": 100002, "status": "passed"},
        ],
    )
    add_two_passed_response()


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.parametrize("fake_incident_1_failed_2_passed", [1005], indirect=True)
@pytest.mark.usefixtures(
    "fake_qem",
    "fake_incident_1_failed_2_passed",
    "fake_two_passed_jobs",
    "fake_openqa_comment_api",
    "fake_responses_updating_job",
)
def test_one_incident_failed(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    assert approver() == 0
    assert len(caplog.records) >= 1, "we rely on log messages in tests"
    messages = [x[-1] for x in caplog.record_tuples]
    assert "SUSE:Maintenance:1:100 has at least one failed job in incident tests" in messages
    assert "Found failed, not-ignored job http://instance.qa/t100001 for incident 1" in messages
    assert "* SUSE:Maintenance:2:200" in messages
    assert "* SUSE:Maintenance:3:300" in messages
    assert "* SUSE:Maintenance:4:400" in messages
    assert "Incidents to approve:" in messages
    assert "End of bot run" in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures(
    "fake_qem",
    "fake_openqa_comment_api",
    "fake_responses_updating_job",
    "fake_openqa_older_jobs_api",
)
def test_one_aggr_failed(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    responses.add(
        responses.GET,
        f"{QEM_DASHBOARD}api/jobs/update/20005",
        json=[
            {"job_id": 100000, "status": "passed"},
            {"job_id": 100001, "status": "failed"},
            {"job_id": 100002, "status": "passed"},
        ],
    )
    add_two_passed_response()
    assert approver() == 0
    assert len(caplog.records) >= 1, "we rely on log messages in tests"
    messages = [x[-1] for x in caplog.record_tuples]
    assert "SUSE:Maintenance:2:200 has at least one failed job in aggregate tests" in messages
    assert "Found failed, not-ignored job http://instance.qa/t100001 for incident 2" in messages
    assert "* SUSE:Maintenance:1:100" in messages
    assert "* SUSE:Maintenance:3:300" in messages
    assert "* SUSE:Maintenance:4:400" in messages
    assert "Incidents to approve:" in messages
    assert "End of bot run" in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.parametrize(
    "fake_responses_for_unblocking_incidents_via_openqa_comments",
    [{"incident": 2}],
    indirect=True,
)
@pytest.mark.usefixtures(
    "fake_qem",
    "fake_responses_for_unblocking_incidents_via_openqa_comments",
    "fake_openqa_comment_api",
    "fake_openqa_older_jobs_api",
)
def test_approval_unblocked_via_openqa_comment(
    caplog: pytest.LogCaptureFixture,
    fake_dashboard_remarks_api: list[responses.BaseResponse],
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "* SUSE:Maintenance:2:200" in messages, "incident approved as all failures are considered acceptable"
    assert len(fake_dashboard_remarks_api[0].calls) == 0, "passing job not marked as acceptable"
    for index in range(1, 4):
        assert fake_dashboard_remarks_api[index].calls[0] in responses.calls, (
            f"failing job with comment marked as acceptable ({index})"
        )
    assert "Ignoring failed job http://instance.qa/t100002 for incident 2 due to openQA comment" in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.parametrize(
    "fake_responses_for_unblocking_incidents_via_openqa_comments",
    [
        {
            "incident": 2,
            "not_acceptable_job_ids": [100003],
            "acceptable_job_ids": [100002, 100004],
        },
    ],
    indirect=True,
)
@pytest.mark.usefixtures(
    "fake_qem",
    "fake_responses_for_unblocking_incidents_via_openqa_comments",
    "fake_openqa_comment_api",
    "fake_openqa_older_jobs_api",
)
def test_all_jobs_marked_as_acceptable_for_via_openqa_comment(
    caplog: pytest.LogCaptureFixture,
    fake_dashboard_remarks_api: list[responses.BaseResponse],
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "* SUSE:Maintenance:2:200" not in messages, "incident not approved due to one unacceptable failure"
    assert len(fake_dashboard_remarks_api[0].calls) == 0, "passing job not marked as acceptable"
    assert fake_dashboard_remarks_api[1].calls[0] in responses.calls, "failing job with comment marked as acceptable"
    assert len(fake_dashboard_remarks_api[2].calls) == 0, "failing job without comment not marked as acceptable"
    assert fake_dashboard_remarks_api[3].calls[0] in responses.calls, (
        "another failing job with comment marked as acceptable despite previous unacceptable failure"
    )
    assert "Ignoring failed job http://instance.qa/t100002 for incident 2 due to openQA comment" in messages
    assert "Ignoring failed job http://instance.qa/t100004 for incident 2 due to openQA comment" not in messages, (
        "log message only present for jobs before unacceptable failure"
    )


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.parametrize(
    "fake_responses_for_unblocking_incidents_via_openqa_comments",
    [{"incident": 22}],
    indirect=True,
)
@pytest.mark.usefixtures(
    "fake_qem",
    "fake_responses_for_unblocking_incidents_via_openqa_comments",
    "fake_openqa_comment_api",
    "fake_openqa_older_jobs_api",
)
def test_approval_still_blocked_if_openqa_comment_not_relevant(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "* SUSE:Maintenance:2:200" not in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.parametrize("fake_responses_for_unblocking_incidents_via_older_ok_result", [2], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_responses_for_unblocking_incidents_via_older_ok_result")
def test_approval_unblocked_via_openqa_older_ok_job(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    responses.add(
        responses.GET,
        re.compile(f"{QEM_DASHBOARD}api/jobs/100005"),
        json={"status": "passed"},
    )
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "* SUSE:Maintenance:2:200" in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.parametrize("fake_responses_for_unblocking_incidents_via_older_ok_result", [2], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_responses_for_unblocking_incidents_via_older_ok_result")
def test_approval_still_blocked_via_openqa_older_ok_job_because_not_in_dashboard(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    responses.add(
        responses.GET,
        re.compile(f"{QEM_DASHBOARD}api/jobs/100005"),
        json={"error": "Job not found"},
    )
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "* SUSE:Maintenance:2:200" not in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.parametrize(
    "fake_responses_for_unblocking_incidents_via_older_ok_result",
    [2222],
    indirect=True,
)
@pytest.mark.usefixtures("fake_qem", "fake_responses_for_unblocking_incidents_via_older_ok_result")
def test_approval_still_blocked_if_openqa_older_job_dont_include_incident(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "* SUSE:Maintenance:2:200" not in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.parametrize(
    "comment_text",
    [
        "\r\r@review:acceptable_for:incident_2:foo\r",  # Carriage returns
        "Some irrelevant text\n@review:acceptable_for:incident_2:foo",  # Text before @review
        "@review:acceptable_for:incident_2:foo\nSome extra text",  # Trailing characters
        "\x0c@review:acceptable_for:incident_2:foo",  # Non-printable character
    ],
)
@pytest.mark.usefixtures("fake_qem", "fake_openqa_older_jobs_api", "fake_dashboard_remarks_api")
def test_approval_unblocked_with_various_comment_formats(
    comment_text: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    responses.add(
        responses.GET,
        f"{QEM_DASHBOARD}api/jobs/update/20005",
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
        json=[{"text": comment_text}],
    )
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "* SUSE:Maintenance:2:200" in messages
    assert "Ignoring failed job http://instance.qa/t100002 for incident 2 due to openQA comment" in messages
    responses.assert_call_count(
        f"{QEM_DASHBOARD}api/jobs/100002/remarks?text=acceptable_for&incident_number=2",
        1,
    )
