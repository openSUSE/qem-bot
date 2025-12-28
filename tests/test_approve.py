# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# ruff: noqa: S106 "Possible hardcoded password assigned to argument"

import io
import logging
import re
from argparse import Namespace
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, NoReturn
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


@dataclass(frozen=True)
class CommentFormatTestCase:
    comment_text: str
    description: str


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
    assert "Incident approval process finished" in messages
    assert f"* {inc_str}" in messages


def assert_incident_not_approved(messages: list[str], inc_str: str, reason: str) -> None:
    assert reason in messages
    assert "Incidents to approve:" in messages
    assert "Incident approval process finished" in messages
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
def fake_qem(request: pytest.FixtureRequest, mocker: MockerFixture) -> None:
    request_param = request.node.get_closest_marker("qem_behavior").args[0]
    # Inc 1 needs aggregates
    # Inc 2 needs aggregates
    # Inc 3 part needs aggregates
    # Inc 4 dont need aggregates

    def f_inc_settins(inc: int, _token: str, **_kwargs: Any) -> list[JobAggr]:
        if "inc" in request_param:
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
        return results.get(inc, [])

    def f_aggr_settings(inc: int, _token: str) -> list[JobAggr]:
        if "aggr" in request_param:
            msg = "No results for settings"
            raise NoResultsError(msg)
        results = {
            5: [],
            4: [],
            1: [JobAggr(i, aggregate=True, with_aggregate=False) for i in range(10000, 10010)],
            2: [JobAggr(i, aggregate=True, with_aggregate=False) for i in range(20000, 20010)],
            3: [JobAggr(i, aggregate=True, with_aggregate=False) for i in range(30000, 30010)],
        }
        return results.get(inc, [])

    mocker.patch("openqabot.approver.get_single_incident", side_effect=lambda _, i: [f_inc_approver()[i - 1]])
    mocker.patch("openqabot.approver.get_incidents_approver", side_effect=f_inc_approver)
    mocker.patch("openqabot.approver.get_incident_settings", side_effect=f_inc_settins)
    mocker.patch("openqabot.approver.get_aggregate_settings", side_effect=f_aggr_settings)

    # Clear caches to ensure isolation between tests
    from openqabot.approver import Approver
    from openqabot.openqa import openQAInterface

    openQAInterface.get_job_comments.cache_clear()
    openQAInterface.get_single_job.cache_clear()
    openQAInterface.get_older_jobs.cache_clear()
    openQAInterface.is_devel_group.cache_clear()

    Approver.is_job_marked_acceptable_for_incident.cache_clear()
    Approver.validate_job_qam.cache_clear()
    Approver.was_ok_before.cache_clear()
    Approver.get_jobs.cache_clear()


def with_fake_qem(mode: str) -> Any:
    """Local meta-decorator that sets the behavior marker and triggers the fixture injection.

    Use examples:
    @with_fake_qem("NoResultsError isn't raised")
    ...
    @with_fake_qem("inc")
    """

    def decorator(test_func: object) -> object:
        test_func = pytest.mark.qem_behavior(mode)(test_func)
        return pytest.mark.usefixtures("fake_qem")(test_func)

    return decorator


@pytest.fixture
def f_osconf(mocker: MockerFixture) -> Any:
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
@with_fake_qem("NoResultsError isn't raised")
def test_no_jobs(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch("openqabot.approver.get_json", return_value=[])
    approver()
    assert "SUSE:Maintenance:4:400 has at least one failed job in incident tests" in caplog.messages
    assert "Incidents to approve:" in caplog.messages
    assert "Incident approval process finished" in caplog.messages
    assert "* SUSE:Maintenance:4:400" not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_single_incident_mocks")
def test_single_incident_failed_not_approved(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        return [{"incident_settings": int(url.rsplit("/", maxsplit=1)[-1]), "job_id": 100001, "status": "failed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)
    mocker.patch("openqabot.openqa.openQAInterface.get_job_comments", return_value=[])

    approver(incident=1)
    assert_incident_not_approved(
        caplog.messages,
        "SUSE:Maintenance:1:100",
        "SUSE:Maintenance:1:100 has at least one failed job in incident tests",
    )
    assert "Found failed, not-ignored job http://instance.qa/t100001 for incident 1" in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_single_incident_mocks")
def test_single_incident_passed_is_approved(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        return [{"incident_settings": int(url.rsplit("/", maxsplit=1)[-1]), "job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)

    approver(incident=4)
    assert_incident_approved(caplog.messages, "SUSE:Maintenance:4:400")


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs")
def test_all_passed(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    mocker.patch("openqabot.approver.get_json", return_value=[{"job_id": 100000, "status": "passed"}])

    assert approver() == 0
    expected = [
        "* SUSE:Maintenance:1:100",
        "* SUSE:Maintenance:2:200",
        "* SUSE:Maintenance:3:300",
        "* SUSE:Maintenance:4:400",
        "Incidents to approve:",
        "Incident approval process finished",
    ]
    assert_log_messages(caplog.messages, expected)


@responses.activate
@with_fake_qem("aggr")
@pytest.mark.usefixtures("fake_two_passed_jobs")
def test_inc_passed_aggr_without_results(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    mocker.patch("openqabot.approver.get_json", return_value=[{"job_id": 100000, "status": "passed"}])

    assert approver() == 0
    expected = [
        "No aggregate test results found for SUSE:Maintenance:1:100",
        "No aggregate test results found for SUSE:Maintenance:2:200",
        "No aggregate test results found for SUSE:Maintenance:3:300",
        "Starting approving incidents in IBS or Gitea…",
        "Incidents to approve:",
        "* SUSE:Maintenance:4:400",
        "Incident approval process finished",
    ]
    assert_log_messages(caplog.messages, expected)


@responses.activate
@with_fake_qem("inc")
@pytest.mark.usefixtures("fake_two_passed_jobs")
def test_inc_without_results(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    mocker.patch("openqabot.approver.get_json", return_value=[{"job_id": 100000, "status": "passed"}])

    assert approver() == 0
    expected = [
        "Starting approving incidents in IBS or Gitea…",
        "Incidents to approve:",
        "Incident approval process finished",
    ]
    assert_log_messages(caplog.messages, expected)
    assert "* SUSE:Maintenance" not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs", "fake_responses_for_creating_pr_review", "f_osconf")
def test_403_response(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.GIT_REVIEW_BOT", "")
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch("osc.core.change_review_state", side_effect=ObsHTTPError(403, "Not allowed", "sd", None))
    assert Approver(args)() == 0
    assert "Received 'Not allowed'. Request 100 likely already approved, ignoring" in caplog.messages, (
        "Expected handling of 403 responses logged"
    )


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs", "f_osconf")
def test_404_response(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch(
        "osc.core.change_review_state", side_effect=ObsHTTPError(404, "Not Found", None, io.BytesIO(b"review state"))
    )
    assert Approver(args)() == 1
    assert "OBS API error for request 100 (removed or server issue): Not Found - review state" in caplog.messages, (
        "Expected handling of 404 responses logged"
    )


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs", "f_osconf")
def test_500_response(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mocker.patch("osc.core.change_review_state", side_effect=ObsHTTPError(500, "Not allowed", "sd", None))
    assert Approver(args)() == 1
    assert "OBS API error for request 400: 500 - Not allowed" in caplog.messages, (
        "Expected handling of 500 responses logged"
    )


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
    mocker.patch("openqabot.loader.gitea.GIT_REVIEW_BOT", "")
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    mocker.patch("openqabot.approver.get_json", return_value=[{"job_id": 100000, "status": "passed"}])
    mocker.patch("osc.core.change_review_state")
    mock_review_pr = mocker.patch("openqabot.approver.review_pr")

    assert Approver(args)() == 0
    expected = [
        "Incidents to approve:",
        "Incident approval process finished",
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
    mock_review_pr.assert_called_once()


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_two_passed_jobs", "fake_openqa_comment_api", "fake_responses_updating_job")
def test_one_incident_failed(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    # Mock dashboard results: Incident 1 fails, others pass
    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if url == "api/jobs/incident/1000":
            return [
                {"job_id": 100000, "status": "passed"},
                {"job_id": 100001, "status": "failed"},
                {"job_id": 100002, "status": "passed"},
            ]
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)

    assert approver() == 0
    expected = [
        "SUSE:Maintenance:1:100 has at least one failed job in incident tests",
        "Found failed, not-ignored job http://instance.qa/t100001 for incident 1",
        "* SUSE:Maintenance:2:200",
        "* SUSE:Maintenance:3:300",
        "* SUSE:Maintenance:4:400",
        "Incidents to approve:",
        "Incident approval process finished",
    ]
    assert_log_messages(caplog.messages, expected)


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.usefixtures(
    "fake_openqa_comment_api",
    "fake_responses_updating_job",
    "fake_openqa_older_jobs_api",
)
def test_one_aggr_failed(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    # Mock dashboard results: Aggregate jobs for Incident 2 fail, others pass
    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if url.startswith("api/jobs/update/") and "2000" in url:
            return [
                {"job_id": 100000, "status": "passed"},
                {"job_id": 100001, "status": "failed"},
                {"job_id": 100002, "status": "passed"},
            ]
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)

    assert approver() == 0
    expected = [
        "SUSE:Maintenance:2:200 has at least one failed job in aggregate tests",
        "Found failed, not-ignored job http://instance.qa/t100001 for incident 2",
        "* SUSE:Maintenance:1:100",
        "* SUSE:Maintenance:3:300",
        "* SUSE:Maintenance:4:400",
        "Incidents to approve:",
        "Incident approval process finished",
    ]
    assert_log_messages(caplog.messages, expected)


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.parametrize(
    "fake_responses_for_unblocking_incidents_via_openqa_comments",
    [{"incident": 2}],
    indirect=True,
)
@pytest.mark.usefixtures(
    "fake_responses_for_unblocking_incidents_via_openqa_comments",
    "fake_openqa_comment_api",
    "fake_openqa_older_jobs_api",
)
def test_approval_unblocked_via_openqa_comment(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "update/2000" in url:
            return [
                {"job_id": 100000, "status": "passed"},
                {"job_id": 100002, "status": "failed"},
                {"job_id": 100003, "status": "failed"},
                {"job_id": 100004, "status": "failed"},
            ]
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)
    comments_return_value = [{"text": "@review:acceptable_for:incident_2:foo"}]
    mocker.patch("openqabot.openqa.openQAInterface.get_job_comments", return_value=comments_return_value)
    mock_patch = mocker.patch("openqabot.approver.patch")

    assert approver() == 0
    expected = [
        "* SUSE:Maintenance:2:200",
        "Ignoring failed job http://instance.qa/t100002 for incident 2 (manually marked as acceptable)",
    ]
    assert_log_messages(caplog.messages, expected)

    expected_url = "api/jobs/100002/remarks?text=acceptable_for&incident_number=2"
    mock_patch.assert_any_call(expected_url, headers=mocker.ANY)


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
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
    "fake_responses_for_unblocking_incidents_via_openqa_comments",
    "fake_openqa_comment_api",
    "fake_openqa_older_jobs_api",
)
def test_all_jobs_marked_as_acceptable_for_via_openqa_comment(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "update/2000" in url:
            return [
                {"job_id": 100000, "status": "passed"},
                {"job_id": 100002, "status": "failed"},
                {"job_id": 100003, "status": "failed"},
                {"job_id": 100004, "status": "failed"},
            ]
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)

    def mock_get_job_comments(job_id: int) -> list[dict[str, str]]:
        if job_id in {100002, 100004}:
            return [{"text": "@review:acceptable_for:incident_2:foo"}]
        return []

    mocker.patch("openqabot.openqa.openQAInterface.get_job_comments", side_effect=mock_get_job_comments)
    mock_patch = mocker.patch("openqabot.approver.patch")

    assert approver() == 0
    expected = [
        "Ignoring failed job http://instance.qa/t100002 for incident 2 (manually marked as acceptable)",
    ]
    assert_log_messages(caplog.messages, expected)
    assert "* SUSE:Maintenance:2:200" not in caplog.messages, "incident not approved due to one unacceptable failure"

    mock_patch.assert_any_call("api/jobs/100002/remarks?text=acceptable_for&incident_number=2", headers=mocker.ANY)
    mock_patch.assert_any_call("api/jobs/100004/remarks?text=acceptable_for&incident_number=2", headers=mocker.ANY)

    for call in mock_patch.call_args_list:
        assert "100003" not in call[0][0]
        assert "100000" not in call[0][0]


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.parametrize(
    "fake_responses_for_unblocking_incidents_via_openqa_comments",
    [{"incident": 22}],
    indirect=True,
)
@pytest.mark.usefixtures(
    "fake_responses_for_unblocking_incidents_via_openqa_comments",
    "fake_openqa_comment_api",
    "fake_openqa_older_jobs_api",
)
def test_approval_still_blocked_if_openqa_comment_not_relevant(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "update/2000" in url:
            return [
                {"job_id": 100000, "status": "passed"},
                {"job_id": 100002, "status": "failed"},
            ]
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)
    comments_return_value = [{"text": "@review:acceptable_for:incident_22:foo"}]
    mocker.patch("openqabot.openqa.openQAInterface.get_job_comments", return_value=comments_return_value)

    assert approver() == 0
    assert "* SUSE:Maintenance:2:200" not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.parametrize("fake_responses_for_unblocking_incidents_via_older_ok_result", [2], indirect=True)
@pytest.mark.usefixtures("fake_responses_for_unblocking_incidents_via_older_ok_result")
@pytest.mark.parametrize(
    ("mock_json", "approved"),
    [
        ({"status": "passed"}, True),
        ({"error": "Job not found"}, False),
    ],
    ids=["job_passed", "job_not_found"],
)
def test_approval_via_openqa_older_ok_job(
    caplog: pytest.LogCaptureFixture, mock_json: dict, *, approved: bool, mocker: MockerFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "update/2000" in url:
            return [{"job_id": 100002, "status": "failed"}]
        if url == "api/jobs/100005":
            return mock_json
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)
    mocker.patch(
        "openqabot.openqa.openQAInterface.get_older_jobs",
        return_value={
            "data": [
                {"build": "20240115-1", "id": 100002, "result": "failed"},
                {"build": "20240114-1", "id": 100005, "result": "passed"},
            ]
        },
    )
    mocker.patch(
        "openqabot.openqa.openQAInterface.get_single_job",
        return_value={"settings": {"BASE_TEST_REPOS": "Maintenance:/2/"}},
    )

    assert approver() == 0

    log_message = "* SUSE:Maintenance:2:200"
    assert log_message in caplog.messages if approved else log_message not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.parametrize("fake_responses_for_unblocking_incidents_via_older_ok_result", [2], indirect=True)
@pytest.mark.usefixtures("fake_responses_for_unblocking_incidents_via_older_ok_result")
def test_approval_still_blocked_via_openqa_older_ok_job_because_not_in_dashboard(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    def mock_get_json(url: str, **_kwargs: Any) -> Any:
        if "update/2000" in url:
            return [{"job_id": 100002, "status": "failed"}]
        if url == "api/jobs/100005":
            return {"error": "Job not found"}
        return [{"job_id": 100000, "status": "passed"}]

    mocker.patch("openqabot.approver.get_json", side_effect=mock_get_json)
    mocker.patch(
        "openqabot.openqa.openQAInterface.get_older_jobs",
        return_value={
            "data": [
                {"build": "20240115-1", "id": 100002, "result": "failed"},
                {"build": "20240114-1", "id": 100005, "result": "passed"},
            ]
        },
    )
    mocker.patch(
        "openqabot.openqa.openQAInterface.get_single_job",
        return_value={"settings": {"BASE_TEST_REPOS": "Maintenance:/2/"}},
    )

    assert approver() == 0
    assert "* SUSE:Maintenance:2:200" not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
@pytest.mark.parametrize(
    "fake_responses_for_unblocking_incidents_via_older_ok_result",
    [2222],
    indirect=True,
)
@pytest.mark.usefixtures("fake_responses_for_unblocking_incidents_via_older_ok_result")
def test_approval_still_blocked_if_openqa_older_job_dont_include_incident(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    assert approver() == 0
    assert "* SUSE:Maintenance:2:200" not in caplog.messages


@responses.activate
@with_fake_qem("NoResultsError isn't raised")
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
@pytest.mark.usefixtures("fake_openqa_older_jobs_api")
def test_approval_unblocked_with_various_comment_formats(
    case: CommentFormatTestCase, caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mock_get_json = mocker.patch("openqabot.approver.get_json")

    def side_effect_get_json(url: str, **_kwargs: Any) -> Any:
        if url == "api/jobs/update/20005":
            return [
                {"job_id": 100000, "status": "passed"},
                {"job_id": 100002, "status": "failed"},
                {"job_id": 100003, "status": "passed"},
            ]
        return [{"status": "passed"}, {"status": "passed"}]

    mock_get_json.side_effect = side_effect_get_json

    mocker.patch(
        "openqabot.openqa.openQAInterface.get_job_comments",
        return_value=[{"text": case.comment_text}],
    )
    mock_patch = mocker.patch("openqabot.approver.patch")

    assert approver() == 0
    assert "* SUSE:Maintenance:2:200" in caplog.messages
    assert (
        "Ignoring failed job http://instance.qa/t100002 for incident 2 (manually marked as acceptable)"
        in caplog.messages
    )

    expected_url = "api/jobs/100002/remarks?text=acceptable_for&incident_number=2"
    mock_patch.assert_called_once_with(expected_url, headers=mocker.ANY)


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
    assert any(log_message in m for m in caplog.messages)


@pytest.mark.parametrize(
    ("older_jobs_data", "log_message"),
    [
        pytest.param(
            {"build": "20240101XY", "result": "failed", "id": 123},
            "No suitable older jobs found",
            id="no_suitable_older_jobs",
        ),
        pytest.param(
            {"build": "invalid-date"},
            "Could not parse build date",
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
    assert any(log_message in m for m in caplog.messages)


def test_git_approve_no_url(caplog: pytest.LogCaptureFixture) -> None:
    approver_instance = Approver(args)
    inc = IncReq(inc=1, req=100, type="git", url=None)
    caplog.set_level(logging.ERROR)
    assert not approver_instance.git_approve(inc, "msg")
    assert "Gitea API error: PR 1 has no URL" in caplog.text


def test_get_incident_result_empty_jobs() -> None:
    approver_instance = Approver(args)
    assert approver_instance.get_incident_result([], "api/", 1) is False
