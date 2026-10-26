# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test approve helpers."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, NoReturn

import pytest
import requests
from openqa_client.exceptions import RequestError

from openqabot.approver import Approver, JobResult, OlderJobResult, mark_job_as_acceptable_for_submission
from openqabot.loader.qem import JobAggr, SubReq
from openqabot.types.pullrequest import PullRequest
from openqabot.types.submission_key import SubmissionKey

from .helpers import GITEA_PR_COMMIT, args, make_approver_args

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _pull_request(head: str) -> PullRequest:
    """Return a fake open Gitea PR whose head commit is ``head``."""
    return PullRequest(
        number=5,
        state="open",
        project="products/SLFO",
        branch="main",
        url="https://src.suse.de/products/SLFO/pulls/5",
        commit_sha=head,
        raw_labels=[],
    )


def test_is_job_marked_acceptable_for_submission_request_error(mocker: MockerFixture) -> None:
    mocker.patch(
        "openqabot.openqa.OpenQAInterface.get_job_comments",
        side_effect=RequestError("Get out", url="http://foo.bar", status_code=404, text="Not Found"),
    )
    approver_instance = Approver(args)
    assert not approver_instance.is_job_marked_acceptable_for_submission(1, 1)


def test_mark_job_as_acceptable_for_submission_request_error(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    def f_patch(*_args: Any, **_kwds: Any) -> NoReturn:
        msg = "Patch failed"
        raise requests.exceptions.RequestException(msg)

    caplog.set_level(logging.INFO)
    mocker.patch("openqabot.approver.dashboard.patch", side_effect=f_patch)
    mark_job_as_acceptable_for_submission(1, SubmissionKey("smelt", "SUSE:Maintenance:1", 1))
    assert "Unable to mark job 1 as acceptable for submission smelt:SUSE:Maintenance:1:1" in caplog.text


def test_mark_job_as_acceptable_for_submission_with_project(mocker: MockerFixture) -> None:
    mock_patch = mocker.patch("openqabot.approver.dashboard.patch")

    mark_job_as_acceptable_for_submission(1, SubmissionKey("smelt", "SUSE:Maintenance:2", 2))

    assert mock_patch.call_args.kwargs["params"] == {
        "text": "acceptable_for",
        "incident_number": "2",
        "project": "SUSE:Maintenance:2",
        "type": "smelt",
    }


def test_mark_job_as_acceptable_for_submission_ok_status(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    mock_patch = mocker.patch("openqabot.approver.dashboard.patch")
    mock_patch.return_value.status_code = HTTPStatus.OK

    mark_job_as_acceptable_for_submission(1, SubmissionKey("smelt", "SUSE:Maintenance:2", 2))

    assert "Unable to mark job" not in caplog.text


def test_approver_stores_single_key_and_all_submissions() -> None:
    key = SubmissionKey("smelt", "SUSE:Maintenance:1", 1)

    numbered = Approver(make_approver_args(), single_submission=key, all_submissions=True)

    assert numbered.single_key == key
    assert numbered.all_submissions is True
    assert Approver(make_approver_args()).single_key is None


def test_approver_single_submission_not_found(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.approver.get_single_submission", return_value=[])
    key = SubmissionKey("smelt", "SUSE:Maintenance:1", 1)

    approver_instance = Approver(make_approver_args(), single_submission=key)

    assert approver_instance() == 1


@pytest.mark.parametrize(
    "json_data", [pytest.param(None, id="no_qam_data"), pytest.param({"status": "failed"}, id="status_not_passed")]
)
def test_validate_job_qam_no_qam_data(json_data: dict, mocker: MockerFixture) -> None:
    approver_instance = Approver(args)
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=json_data)
    assert not approver_instance.validate_job_qam(1)


@pytest.mark.parametrize(
    ("job", "log_message", "expected"),
    [
        (
            {"build": "invalid-date", "result": "passed", "id": 123},
            "Could not parse build date",
            OlderJobResult.KEEP_SEARCHING,
        ),
        ({"build": "20200101-1", "result": "passed", "id": 123}, "Older jobs are too old", OlderJobResult.NOT_OK),
    ],
)
def test_was_older_job_ok_returns_none(
    job: dict, log_message: str, expected: OlderJobResult, caplog: pytest.LogCaptureFixture
) -> None:
    approver_instance = Approver(args)
    oldest_build_usable = datetime.now(UTC) - timedelta(days=1)

    caplog.set_level(logging.INFO)
    assert approver_instance.was_older_job_ok(1, 1, job, oldest_build_usable) is expected
    assert any(log_message in m for m in caplog.messages)


@pytest.mark.parametrize(
    ("older_jobs_data", "log_message"),
    [
        pytest.param(
            [{"build": "20240101XY", "result": "failed", "id": 123}],
            "No suitable older jobs found",
            id="no_suitable_older_jobs",
        ),
        pytest.param(
            [{"build": "invalid-date"}],
            "Could not parse build date",
            id="invalid_date",
        ),
        pytest.param(
            [],
            "Cannot find older jobs for not-ok job 1",
            id="empty_data",
        ),
    ],
)
def test_was_ok_before_no_suitable_older_jobs(
    older_jobs_data: list[dict], log_message: str, caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    approver_instance = Approver(args)
    caplog.set_level(logging.INFO)
    mocker.patch("openqabot.openqa.OpenQAInterface.get_older_jobs", return_value={"data": older_jobs_data})
    mocker.patch("openqabot.approver.Approver.was_older_job_ok")
    assert not approver_instance.was_ok_before(1, 1)
    assert any(log_message in m for m in caplog.messages)


def test_reject_calls_update_incident_reason(mocker: MockerFixture) -> None:
    approver = Approver(make_approver_args())
    approver.dry = False
    mock_update = mocker.patch("openqabot.approver.update_incident_reason")
    sub = SubReq(1, 2, type="smelt", project="SUSE:Maintenance:1")
    assert approver._reject(sub, "Reason %s") is False  # ruff: ignore[private-member-access]
    mock_update.assert_called_once_with(sub.key, "Reason smelt:SUSE:Maintenance:1:1")


def test_reject_dry_run_skips_update_incident_reason(mocker: MockerFixture) -> None:
    approver = Approver(make_approver_args())
    approver.dry = True
    mock_update = mocker.patch("openqabot.approver.update_incident_reason")
    sub = SubReq(1, 2, type="smelt", project="SUSE:Maintenance:1")
    assert approver._reject(sub, "Reason %s") is False  # ruff: ignore[private-member-access]
    mock_update.assert_not_called()


def test_approvable_clears_reason(mocker: MockerFixture) -> None:
    approver = Approver(make_approver_args())
    approver.dry = False
    mock_update = mocker.patch("openqabot.approver.update_incident_reason")
    mock_settings = mocker.patch(
        "openqabot.approver.get_submission_settings",
        return_value=[JobAggr(1, aggregate=False, with_aggregate=False)],
    )
    mocker.patch("openqabot.approver.get_aggregate_settings", return_value=[])
    mocker.patch.object(approver, "get_submission_result", return_value=JobResult.PASSED)

    sub = SubReq(1, 2, type="smelt", project="SUSE:Maintenance:1", scminfo="deadbeef")
    assert approver.approvable(sub) is True
    mock_update.assert_called_once_with(sub.key, None)
    mock_settings.assert_called_once_with(sub.key, all_submissions=False, scminfo="deadbeef")
    approver_instance = Approver(args)
    assert approver_instance.get_submission_result([], "api/", sub.key) is JobResult.NO_JOBS


def test_approvable_skips_without_tested_commit_settings(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """A Gitea PR whose recorded commit has no settings yet is not approved."""
    caplog.set_level(logging.INFO, logger="bot.approver")
    approver = Approver(make_approver_args())
    mocker.patch("openqabot.approver.get_open_prs", return_value=[_pull_request(GITEA_PR_COMMIT)])
    mocker.patch("openqabot.approver.get_submission_settings", return_value=[])
    mock_update = mocker.patch("openqabot.approver.update_incident_reason")

    sub = SubReq(5, 500, type="git", project="products/SLFO", scminfo=GITEA_PR_COMMIT)
    assert approver.approvable(sub) is False
    mock_update.assert_not_called()
    assert f"Approval check for {sub.key} skipped: no tests for the tested commit yet" in caplog.text


def test_approvable_defers_when_pr_head_moved(mocker: MockerFixture) -> None:
    """A PR pushed past the tested commit is not approved with the old results."""
    approver = Approver(make_approver_args())
    mocker.patch("openqabot.approver.get_open_prs", return_value=[_pull_request("newer")])
    mock_settings = mocker.patch("openqabot.approver.get_submission_settings")

    sub = SubReq(5, 500, type="git", project="products/SLFO", scminfo=GITEA_PR_COMMIT)

    assert approver.approvable(sub) is False
    mock_settings.assert_not_called()


@pytest.mark.parametrize(
    ("prs", "scminfo", "expected", "message"),
    [
        pytest.param([], None, False, "cannot read the head commit", id="no_pr"),
        pytest.param([], GITEA_PR_COMMIT, False, "cannot read the head commit", id="no_pr_with_scminfo"),
        pytest.param([None], None, False, "cannot read the head commit", id="unknown_head"),
        pytest.param([GITEA_PR_COMMIT], None, True, "revisions cannot be told apart", id="no_scminfo"),
        pytest.param([GITEA_PR_COMMIT], GITEA_PR_COMMIT, True, None, id="head_is_tested_commit"),
        pytest.param([GITEA_PR_COMMIT], "other", False, "approval deferred", id="head_moved"),
    ],
)
def test_head_matches_tested_commit(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    prs: list[str | None],
    scminfo: str | None,
    *,
    expected: bool,
    message: str | None,
) -> None:
    approver = Approver(make_approver_args())
    pull_requests = [_pull_request(head or "unknown") for head in prs]
    mocker.patch("openqabot.approver.get_open_prs", return_value=pull_requests)
    caplog.set_level(logging.DEBUG, logger="bot.approver")

    sub = SubReq(5, 500, type="git", project="products/SLFO", scminfo=scminfo)

    assert approver.head_matches_tested_commit(sub) is expected
    if message:
        assert message in caplog.text


def test_head_matches_tested_commit_ignores_non_gitea(mocker: MockerFixture) -> None:
    mock_prs = mocker.patch("openqabot.approver.get_open_prs")
    approver = Approver(make_approver_args())

    assert approver.head_matches_tested_commit(SubReq(1, 2, type="smelt", project="SUSE:Maintenance:1")) is True
    mock_prs.assert_not_called()


def test_job_contains_submission_no_job_settings(mocker: MockerFixture) -> None:
    approver_instance = Approver(args)
    mocker.patch("openqabot.openqa.OpenQAInterface.get_single_job", return_value=None)
    assert not approver_instance.job_contains_submission(1, 1)


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_latest_passes_approves(mocker: MockerFixture) -> None:
    """Test that when a failed job is cloned and the clone passes, approval succeeds."""
    mock_job_results = [
        {"job_id": 20252358, "status": "failed", "name": "scenario1"},
        {"job_id": 20256065, "status": "passed", "name": "scenario1"},
    ]
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=mock_job_results)
    approver = Approver(make_approver_args())
    mock_aggr = JobAggr(id=1000, aggregate=False, with_aggregate=True)
    result = approver.get_jobs(mock_aggr, "api/jobs/incident/", SubmissionKey("smelt", "SUSE:Maintenance:1", 1))
    assert result is JobResult.PASSED


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_latest_fails_blocks(mocker: MockerFixture) -> None:
    """Test that when the latest job fails, approval is blocked."""
    mock_job_results = [
        {"job_id": 20252358, "status": "passed", "name": "scenario1"},
        {"job_id": 20256065, "status": "failed", "name": "scenario1"},
    ]
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=mock_job_results)
    mocker.patch.object(Approver, "was_ok_before", return_value=False)
    mocker.patch.object(Approver, "is_job_marked_acceptable_for_submission", return_value=False)
    approver = Approver(make_approver_args())
    mock_aggr = JobAggr(id=1000, aggregate=False, with_aggregate=True)
    result = approver.get_jobs(mock_aggr, "api/jobs/incident/", SubmissionKey("smelt", "SUSE:Maintenance:1", 1))
    assert result is JobResult.FAILED


def test_validate_job_qam_not_passed(mocker: MockerFixture) -> None:
    mock_data = {"status": "failed", "id": 123}
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=mock_data)

    approver_instance = Approver(args)

    assert approver_instance.validate_job_qam(123) is False


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_different_scenarios(mocker: MockerFixture) -> None:
    """Test that different scenarios are handled independently."""
    mock_job_results = [
        {"job_id": 20252358, "status": "failed", "name": "sc1"},
        {"job_id": 20256065, "status": "passed", "name": "sc1"},
        {"job_id": 20252359, "status": "failed", "name": "sc2"},
        {"job_id": 20256066, "status": "passed", "name": "sc2"},
    ]
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=mock_job_results)
    approver = Approver(make_approver_args())
    mock_aggr = JobAggr(id=1000, aggregate=False, with_aggregate=True)
    result = approver.get_jobs(mock_aggr, "api/jobs/incident/", SubmissionKey("smelt", "SUSE:Maintenance:1", 1))
    assert result is JobResult.PASSED


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_two_scenarios_one_fails_blocks(mocker: MockerFixture) -> None:
    """Test that if one scenario fails (even with older ID), approval is blocked."""
    mock_job_results = [
        {"job_id": 1000, "status": "passed", "name": "scenario1"},
        {"job_id": 500, "status": "failed", "name": "scenario2"},
    ]
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=mock_job_results)
    mocker.patch.object(Approver, "is_job_marked_acceptable_for_submission", return_value=False)
    approver = Approver(make_approver_args())
    mock_aggr = JobAggr(id=1000, aggregate=False, with_aggregate=True)
    result = approver.get_jobs(mock_aggr, "api/jobs/incident/", SubmissionKey("smelt", "SUSE:Maintenance:1", 1))
    assert result is JobResult.FAILED


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_fallback_to_other_urls(mocker: MockerFixture) -> None:
    """Test that non-incident URLs return fallback results."""
    mock_job_results = [
        {"job_id": 20252358, "status": "failed", "name": "sc1"},
        {"job_id": 20256065, "status": "passed", "name": "sc1"},
    ]
    fallback_results = [{"job_id": 100000, "status": "passed"}]

    def mock_get_json(url: str, **_kwargs: object) -> list[dict]:
        return mock_job_results if "incident" in url else fallback_results

    mocker.patch("openqabot.approver.dashboard.get_json", side_effect=mock_get_json)
    approver = Approver(make_approver_args())
    mock_aggr = JobAggr(id=1000, aggregate=False, with_aggregate=True)
    result_incident = approver.get_jobs(
        mock_aggr, "api/jobs/incident/", SubmissionKey("smelt", "SUSE:Maintenance:1", 1)
    )
    result_update = approver.get_jobs(mock_aggr, "api/jobs/update/", SubmissionKey("smelt", "SUSE:Maintenance:1", 1))
    assert result_incident is JobResult.PASSED
    assert result_update is JobResult.PASSED


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_empty_results(mocker: MockerFixture) -> None:
    """Test that None is returned when no job results are found."""
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=[])
    approver = Approver(make_approver_args())
    mock_aggregates = [JobAggr(id=1, aggregate=False, with_aggregate=True)]
    result = approver.get_jobs(mock_aggregates[0], "api/jobs/update/", SubmissionKey("smelt", "SUSE:Maintenance:1", 1))
    assert result is JobResult.NO_JOBS


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_error_results(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    """Test that None is returned when job results contain error."""
    caplog.set_level(logging.DEBUG, logger="bot.approver")
    mock_job_results = {"error": "Not found"}
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=mock_job_results)
    approver = Approver(make_approver_args())
    mock_aggregates = [JobAggr(id=1, aggregate=False, with_aggregate=True)]
    result = approver.get_jobs(mock_aggregates[0], "api/jobs/update/", SubmissionKey("smelt", "SUSE:Maintenance:1", 1))
    assert result is JobResult.NO_JOBS
    assert any("Unexpected job results format" in msg for msg in caplog.messages)


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_jobs_without_job_id(mocker: MockerFixture) -> None:
    """Test that jobs without job_id are handled correctly during deduplication."""
    mock_job_results = [
        {"job_id": 100, "status": "passed", "name": "scenario1"},
        {"status": "passed", "name": "scenario2"},
    ]
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=mock_job_results)
    approver = Approver(make_approver_args())
    mock_aggregates = [JobAggr(id=1, aggregate=False, with_aggregate=True)]
    result = approver.get_jobs(mock_aggregates[0], "api/jobs/update/", SubmissionKey("smelt", "SUSE:Maintenance:1", 1))
    assert result is JobResult.PASSED


@pytest.mark.qem_behavior("NoResultsError isn't raised")
@pytest.mark.usefixtures("fake_qem")
def test_clone_dedup_keeps_highest_job_id(mocker: MockerFixture) -> None:
    """Test that deduplication keeps highest job_id even when lower job_id comes later in list."""
    mock_job_results = [
        {"job_id": 101, "status": "passed", "name": "scenario1"},
        {"job_id": 100, "status": "failed", "name": "scenario1"},
    ]
    mocker.patch("openqabot.approver.dashboard.get_json", return_value=mock_job_results)
    approver = Approver(make_approver_args())
    mock_aggregates = [JobAggr(id=1, aggregate=False, with_aggregate=True)]
    result = approver.get_jobs(mock_aggregates[0], "api/jobs/update/", SubmissionKey("smelt", "SUSE:Maintenance:1", 1))
    assert result is JobResult.PASSED
