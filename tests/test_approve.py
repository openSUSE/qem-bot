# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# ruff: noqa: S106 "Possible hardcoded password assigned to argument"

import io
import logging
import re
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, NamedTuple, NoReturn
from urllib.error import HTTPError
from urllib.parse import urlparse

import pytest
from openqa_client.exceptions import RequestError
from pytest_mock import MockerFixture

import responses
from openqabot.approver import QEM_DASHBOARD, Approver
from openqabot.errors import NoResultsError
from openqabot.loader.qem import IncReq, JobAggr
from openqabot.utc import UTC
from responses import matchers


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


@dataclass(frozen=True)
class CommentFormatTestCase:
    comment_text: str
    description: str


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


def add_two_passed_response() -> None:
    responses.add(
        responses.GET,
        re.compile(f"{QEM_DASHBOARD}api/jobs/.*/.*"),
        json=[{"status": "passed"}, {"status": "passed"}],
    )


def assert_incident_approved(messages: list[str], inc_str: str) -> None:
    assert f"{inc_str} has at least one failed job in incident tests" not in messages
    assert "Incidents to approve:" in messages
    assert "End of bot run" in messages
    assert f"* {inc_str}" in messages


def assert_incident_not_approved(messages: list[str], inc_str: str, reason: str) -> None:
    assert reason in messages
    assert "Incidents to approve:" in messages
    assert "End of bot run" in messages
    assert f"* {inc_str}" not in messages


def assert_log_messages(messages: list[str], expected_messages: list[str]) -> None:
    for msg in expected_messages:
        assert msg in messages


class ObsHTTPError(HTTPError):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__("Fake OBS", *args, **kwargs)


class ArbitraryObsError(Exception):
    def __init__(self) -> None:
        super().__init__("Fake OBS exception")


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
                {"build": "20251201-1", "id": 100005, "result": "softfailed"},  # Fixed 'build' type
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
def fake_dashboard_remarks_api() -> list[responses.BaseResponse]:
    return [
        responses.patch(
            f"{QEM_DASHBOARD}api/jobs/{job_id}/remarks?text=acceptable_for&incident_number=2",
            json=[{}],
        )
        for job_id in [100001, 100002, 100003, 100004]
    ]


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
def fake_qem(request: pytest.FixtureRequest, mocker: MockerFixture) -> Generator[None, None, None]:
    # Inc 1 needs aggregates
    # Inc 2 needs aggregates
    # Inc 3 part needs aggregates
    # Inc 4 dont need aggregates

    def f_inc_settins(inc: int, _token: str, **_kwargs: Any) -> list[JobAggr]:
        if "inc" in request.param:
            msg = "No results for settings"
            raise NoResultsError(msg)
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
            msg = "No results for settings"
            raise NoResultsError(msg)
        results = {
            5: [],
            4: [],
            1: [JobAggr(i, aggregate=True, with_aggregate=False) for i in range(10000, 10010)],
            2: [JobAggr(i, aggregate=True, with_aggregate=False) for i in range(20000, 20010)],
            3: [JobAggr(i, aggregate=True, with_aggregate=False) for i in range(30000, 30010)],
        }
        return results.get(inc)

    mocker.patch("openqabot.approver.get_single_incident", side_effect=f_inc_single_approver)
    mocker.patch("openqabot.approver.get_incidents_approver", side_effect=f_inc_approver)
    mocker.patch("openqabot.approver.get_incident_settings", side_effect=f_inc_settins)
    mocker.patch("openqabot.approver.get_aggregate_settings", side_effect=f_aggr_settings)


@pytest.fixture
def f_osconf(mocker: MockerFixture) -> Generator[None, None, None]:
    return mocker.patch("osc.conf.get_config")


@pytest.fixture
def fake_single_incident_mocks() -> None:
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


@pytest.fixture
def fake_one_aggr_failed_responses() -> None:
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
@pytest.mark.usefixtures("fake_qem", "fake_single_incident_mocks")
def test_single_incident_failed_not_approved(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    approver(incident=1)
    messages = [x[-1] for x in caplog.record_tuples]
    assert_incident_not_approved(
        messages, "SUSE:Maintenance:1:100", "SUSE:Maintenance:1:100 has at least one failed job in incident tests"
    )
    assert "Found failed, not-ignored job http://instance.qa/t100001 for incident 1" in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_single_incident_mocks")
def test_single_incident_passed_is_approved(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    approver(incident=4)
    messages = [x[-1] for x in caplog.record_tuples]
    assert_incident_approved(messages, "SUSE:Maintenance:4:400")


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_two_passed_jobs")
def test_all_passed(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    expected = [
        "* SUSE:Maintenance:1:100",
        "* SUSE:Maintenance:2:200",
        "* SUSE:Maintenance:3:300",
        "* SUSE:Maintenance:4:400",
        "Incidents to approve:",
        "End of bot run",
    ]
    assert_log_messages(messages, expected)


@responses.activate
@pytest.mark.parametrize("fake_qem", ["aggr"], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_two_passed_jobs")
def test_inc_passed_aggr_without_results(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    expected = [
        "Approving incidents in IBS or Gitea…",
        "No aggregate test results found for SUSE:Maintenance:1:100",
        "No aggregate test results found for SUSE:Maintenance:2:200",
        "No aggregate test results found for SUSE:Maintenance:3:300",
        "Incidents to approve:",
        "* SUSE:Maintenance:4:400",
        "End of bot run",
    ]
    assert_log_messages(messages, expected)


@responses.activate
@pytest.mark.parametrize("fake_qem", ["inc"], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_two_passed_jobs")
def test_inc_without_results(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    expected_positive_messages = [
        "Approving incidents in IBS or Gitea…",
        "Incidents to approve:",
        "End of bot run",
    ]
    assert_log_messages(messages, expected_positive_messages)
    assert "* SUSE:Maintenance" not in messages


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures(
    "fake_qem",
    "fake_two_passed_jobs",
    "fake_responses_for_creating_pr_review",
    "f_osconf",
)
def test_403_response(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.GIT_REVIEW_BOT", "")
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch("osc.core.change_review_state", side_effect=ObsHTTPError(403, "Not allowed", "sd", None))
    assert Approver(args)() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Received 'Not allowed'. Request 100 likely already approved, ignoring" in messages, (
        "Expected handling of 403 responses logged"
    )


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_two_passed_jobs", "f_osconf")
def test_404_response(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch(
        "osc.core.change_review_state", side_effect=ObsHTTPError(404, "Not Found", None, io.BytesIO(b"review state"))
    )
    assert Approver(args)() == 1
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Received 'Not Found'. Request 100 removed or problem on OBS side: review state" in messages, (
        "Expected handling of 404 responses logged"
    )


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_two_passed_jobs", "f_osconf")
def test_500_response(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch("osc.core.change_review_state", side_effect=ObsHTTPError(500, "Not allowed", "sd", None))
    assert Approver(args)() == 1
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Received error 500, reason: 'Not allowed' for Request 400 - problem on OBS side" in messages, (
        "Expected handling of 500 responses logged"
    )


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures("fake_qem", "fake_two_passed_jobs", "f_osconf")
def test_osc_unknown_exception(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch("osc.core.change_review_state", side_effect=ArbitraryObsError)
    assert Approver(args)() == 1
    assert "Fake OBS exception" in caplog.text


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures(
    "fake_qem",
    "fake_two_passed_jobs",
    "fake_responses_for_creating_pr_review",
    "f_osconf",
)
def test_osc_all_pass(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.GIT_REVIEW_BOT", "")
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch("osc.core.change_review_state")
    assert Approver(args)() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    expected_messages = [
        "Incidents to approve:",
        "End of bot run",
        "* SUSE:Maintenance:1:100",
        "Accepting review for SUSE:Maintenance:1:100",
        "* SUSE:Maintenance:2:200",
        "Accepting review for SUSE:Maintenance:2:200",
        "* SUSE:Maintenance:3:300",
        "Accepting review for SUSE:Maintenance:3:300",
        "* SUSE:Maintenance:4:400",
        "Accepting review for SUSE:Maintenance:4:400",
        "* git:5",
        "Accepting review for git:5",
    ]
    assert_log_messages(messages, expected_messages)
    assert len(responses.calls) == 76


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures(
    "fake_qem",
    "fake_two_passed_jobs",
    "fake_openqa_comment_api",
    "fake_responses_updating_job",
)
def test_one_incident_failed(caplog: pytest.LogCaptureFixture) -> None:
    responses.add(
        responses.GET,
        f"{QEM_DASHBOARD}api/jobs/incident/1005",
        json=[
            {"job_id": 100000, "status": "passed"},
            {"job_id": 100001, "status": "failed"},
            {"job_id": 100002, "status": "passed"},
        ],
    )
    add_two_passed_response()

    caplog.set_level(logging.DEBUG, logger="bot.approver")
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    expected_messages = [
        "SUSE:Maintenance:1:100 has at least one failed job in incident tests",
        "Found failed, not-ignored job http://instance.qa/t100001 for incident 1",
        "* SUSE:Maintenance:2:200",
        "* SUSE:Maintenance:3:300",
        "* SUSE:Maintenance:4:400",
        "Incidents to approve:",
        "End of bot run",
    ]
    assert_log_messages(messages, expected_messages)


@responses.activate
@pytest.mark.parametrize("fake_qem", ["NoResultsError isn't raised"], indirect=True)
@pytest.mark.usefixtures(
    "fake_qem",
    "fake_openqa_comment_api",
    "fake_responses_updating_job",
    "fake_openqa_older_jobs_api",
    "fake_one_aggr_failed_responses",
)
def test_one_aggr_failed(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    expected_messages = [
        "SUSE:Maintenance:2:200 has at least one failed job in aggregate tests",
        "Found failed, not-ignored job http://instance.qa/t100001 for incident 2",
        "* SUSE:Maintenance:1:100",
        "* SUSE:Maintenance:3:300",
        "* SUSE:Maintenance:4:400",
        "Incidents to approve:",
        "End of bot run",
    ]
    assert_log_messages(messages, expected_messages)


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
    expected_messages = [
        "* SUSE:Maintenance:2:200",
        "Ignoring failed job http://instance.qa/t100002 for incident 2 due to openQA comment",
    ]
    assert_log_messages(messages, expected_messages)
    assert len(fake_dashboard_remarks_api[0].calls) == 0, "passing job not marked as acceptable"
    for index in range(1, 4):
        assert fake_dashboard_remarks_api[index].calls[0] in responses.calls, (
            f"failing job with comment marked as acceptable ({index})"
        )


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
    expected_positive_messages = [
        "Ignoring failed job http://instance.qa/t100002 for incident 2 due to openQA comment",
    ]
    assert_log_messages(messages, expected_positive_messages)
    assert "* SUSE:Maintenance:2:200" not in messages, "incident not approved due to one unacceptable failure"
    assert len(fake_dashboard_remarks_api[0].calls) == 0, "passing job not marked as acceptable"
    assert fake_dashboard_remarks_api[1].calls[0] in responses.calls, "failing job with comment marked as acceptable"
    assert len(fake_dashboard_remarks_api[2].calls) == 0, "failing job without comment not marked as acceptable"
    assert fake_dashboard_remarks_api[3].calls[0] in responses.calls, (
        "another failing job with comment marked as acceptable despite previous unacceptable failure"
    )
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
    "case",
    [
        CommentFormatTestCase(
            comment_text="\r\r@review:acceptable_for:incident_2:foo\r",
            description="with carriage returns",
        ),
        CommentFormatTestCase(
            comment_text="Some irrelevant text\n@review:acceptable_for:incident_2:foo",
            description="with text before @review",
        ),
        CommentFormatTestCase(
            comment_text="@review:acceptable_for:incident_2:foo\nSome extra text",
            description="with trailing characters",
        ),
        CommentFormatTestCase(
            comment_text="\x0c@review:acceptable_for:incident_2:foo",
            description="with non-printable character",
        ),
    ],
    ids=lambda c: c.description,
)
@pytest.mark.usefixtures("fake_qem", "fake_openqa_older_jobs_api", "fake_dashboard_remarks_api")
def test_approval_unblocked_with_various_comment_formats(
    case: CommentFormatTestCase,
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
        json=[{"text": case.comment_text}],
    )
    assert approver() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "* SUSE:Maintenance:2:200" in messages
    assert "Ignoring failed job http://instance.qa/t100002 for incident 2 due to openQA comment" in messages
    responses.assert_call_count(
        f"{QEM_DASHBOARD}api/jobs/100002/remarks?text=acceptable_for&incident_number=2",
        1,
    )


@responses.activate
def test_is_job_marked_acceptable_for_incident_request_error(mocker: MockerFixture) -> None:
    mocker.patch(
        "openqabot.openqa.openQAInterface.get_job_comments",
        side_effect=RequestError("Get out", url="http://foo.bar", status_code=404, text="Not Found"),
    )
    approver_instance = Approver(args)
    assert not approver_instance.is_job_marked_acceptable_for_incident(1, 1)


def test_mark_job_as_acceptable_for_incident_request_error(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    def f_patch(*_args: Any, **_kwds: Any) -> NoReturn:
        msg = "Patch failed"
        raise RequestError(msg, url="http://foo.bar", status_code=500, text="Internal Server Error")

    caplog.set_level(logging.INFO)
    approver_instance = Approver(args)
    mocker.patch("openqabot.approver.patch", side_effect=f_patch)
    approver_instance.mark_job_as_acceptable_for_incident(1, 1)
    assert "Unable to mark job 1 as acceptable for incident 1" in caplog.text


@pytest.mark.parametrize(
    "json_data", [pytest.param(None, id="no_qam_data"), pytest.param({"status": "failed"}, id="status_not_passed")]
)
def test_validate_job_qam_no_qam_data(json_data: dict, mocker: MockerFixture) -> None:
    approver_instance = Approver(args)
    mocker.patch("openqabot.approver.get_json", return_value=json_data)
    assert not approver_instance.validate_job_qam(1)


@pytest.mark.parametrize(
    ("job", "log_message"),
    [
        ({"build": "invalid-date", "result": "passed", "id": 123}, "Could not parse build date"),
        ({"build": "20200101-1", "result": "passed", "id": 123}, "Older jobs are too old"),
    ],
)
def test_was_older_job_ok_returns_none(job: dict, log_message: str, caplog: pytest.LogCaptureFixture) -> None:
    approver_instance = Approver(args)
    oldest_build_usable = datetime.now(UTC) - timedelta(days=1)
    regex = re.compile(r".*")

    caplog.set_level(logging.INFO)
    assert not approver_instance._was_older_job_ok(1, 1, job, oldest_build_usable, regex)  # noqa: SLF001
    assert log_message in caplog.text


@pytest.mark.parametrize(
    ("older_jobs_data", "log_message"),
    [
        pytest.param(
            {"build": "20240101XY", "result": "failed", "id": 123},
            "Older usable jobs did not succeed",
            id="no_suitable_older_jobs",
        ),
        pytest.param(
            {"build": "invalid-date"},
            "Could not parse build date invalid-da",
            id="invalid_date",
        ),
    ],
)
def test_was_ok_before_no_suitable_older_jobs(
    older_jobs_data: dict, log_message: str, caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    approver_instance = Approver(args)
    caplog.set_level(logging.INFO)
    mocker.patch("openqabot.openqa.openQAInterface.get_older_jobs", return_value={"data": [older_jobs_data]})
    mocker.patch("openqabot.approver.Approver._was_older_job_ok")
    assert not approver_instance.was_ok_before(1, 1)
    assert log_message in caplog.text
