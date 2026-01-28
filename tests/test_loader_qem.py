# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
import requests
from pytest_mock import MockerFixture

from openqabot.config import DEFAULT_SUBMISSION_TYPE
from openqabot.loader.qem import (
    LoaderQemError,
    NoAggregateResultsError,
    NoSubmissionResultsError,
    get_active_submissions,
    get_aggregate_results,
    get_aggregate_settings,
    get_aggregate_settings_data,
    get_single_submission,
    get_submission_results,
    get_submission_settings,
    get_submission_settings_data,
    get_submissions,
    get_submissions_approver,
    post_job,
    update_job,
    update_submissions,
)
from openqabot.types.types import Data


@pytest.fixture
def mock_get_json(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("openqabot.loader.qem.get_json")


@pytest.fixture
def mock_patch(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("openqabot.loader.qem.patch")


@pytest.fixture
def mock_put(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("openqabot.loader.qem.put")


def test_get_submissions_simple(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = [
        {
            "id": 1,
            "number": 1,
            "rr_number": 123,
            "project": "project",
            "inReview": True,
            "isActive": True,
            "inReviewQAM": True,
            "approved": False,
            "embargoed": False,
            "channels": ["SUSE:Updates:SLE-Module-Basesystem:15-SP4:x86_64"],
            "packages": ["bar"],
            "emu": False,
        }
    ]

    res = get_submissions({})

    assert len(res) == 1
    assert res[0].id == 1
    mock_get_json.assert_called_once_with("api/incidents", headers={}, verify=True)


def test_get_submissions_on_submission_returns_single_submission(mocker: MockerFixture) -> None:
    get_sub_mock = mocker.patch("openqabot.loader.qem._get_submission")
    get_submissions({}, "git:42")
    get_sub_mock.assert_called_once_with({}, 42, "git")


def test_get_submissions_error(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = {"error": "some error"}
    with pytest.raises(LoaderQemError):
        get_submissions({})


def test_get_submissions_create_none(mock_get_json: MagicMock, mocker: MockerFixture) -> None:
    mock_get_json.return_value = [
        {
            "id": 1,
            "number": 1,
            "rr_number": 123,
            "project": "project",
            "inReview": True,
            "isActive": True,
            "inReviewQAM": True,
            "approved": False,
            "embargoed": False,
            "channels": ["SUSE:Updates:SLE-Module-Basesystem:15-SP4:x86_64"],
            "packages": ["bar"],
            "emu": False,
        }
    ]

    mocker.patch("openqabot.loader.qem.Submission.create", return_value=None)
    res = get_submissions({})
    assert len(res) == 0


def test_get_active_submissions(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = [{"number": 1}, {"number": 2}]

    res = get_active_submissions({}, submission_type="git")

    assert len(res) == 2
    assert res == [1, 2]
    mock_get_json.assert_called_once_with("api/incidents", headers={}, params={"type": "git"})


def test_get_submissions_approver(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = [
        {
            "number": 1,
            "rr_number": 123,
            "inReviewQAM": True,
            "type": "gitea",
            "url": "http://foo.bar",
            "scm_info": "foo",
        },
        {"number": 2, "rr_number": 124, "inReviewQAM": False},
    ]

    res = get_submissions_approver({})

    assert len(res) == 1
    assert res[0].sub == 1
    assert res[0].req == 123
    assert res[0].type == "gitea"
    assert res[0].url == "http://foo.bar"
    assert res[0].scm_info == "foo"


def test_get_single_submission(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = {"number": 1, "rr_number": 123, "type": DEFAULT_SUBMISSION_TYPE}

    res = get_single_submission({}, 1, submission_type=DEFAULT_SUBMISSION_TYPE)

    assert len(res) == 1
    assert res[0].sub == 1
    assert res[0].req == 123
    assert res[0].type == DEFAULT_SUBMISSION_TYPE
    mock_get_json.assert_called_once_with("api/incidents/1", headers={}, params={"type": DEFAULT_SUBMISSION_TYPE})


def test_get_submission_settings_no_settings(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = []

    with pytest.raises(NoSubmissionResultsError):
        get_submission_settings(1, {})

    with pytest.raises(NoSubmissionResultsError):
        get_submission_settings(1, {}, submission_type=DEFAULT_SUBMISSION_TYPE)


def test_get_submission_settings_all_submissions(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = [
        {"id": 1, "settings": {"RRID": 1}, "withAggregate": False},
        {"id": 2, "settings": {"RRID": 2}, "withAggregate": False},
    ]

    res = get_submission_settings(1, {}, all_submissions=True)

    assert len(res) == 2
    assert res[0].id == 1
    assert res[1].id == 2


def test_get_submission_settings_multiple_rrids(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = [
        {"id": 1, "settings": {"RRID": 1}, "withAggregate": False},
        {"id": 2, "settings": {"RRID": 2}, "withAggregate": False},
        {"id": 3, "settings": {}, "withAggregate": False},
    ]

    res = get_submission_settings(1, {}, all_submissions=False)

    assert len(res) == 2
    assert res[0].id == 2
    assert res[1].id == 3


def test_get_submission_settings_no_rrids(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = [
        {"id": 1, "settings": {}, "withAggregate": False},
        {"id": 2, "settings": {}, "withAggregate": False},
    ]

    res = get_submission_settings(1, {}, all_submissions=False)

    assert len(res) == 2


def test_get_submission_settings_data(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = [
        {
            "id": 1,
            "flavor": "flavor",
            "arch": "arch",
            "settings": {"DISTRI": "distri", "BUILD": "build"},
            "version": "version",
        }
    ]

    res = get_submission_settings_data({}, 1, submission_type=DEFAULT_SUBMISSION_TYPE)

    assert len(res) == 1
    assert res[0].submission == 1
    assert res[0].settings_id == 1
    assert res[0].flavor == "flavor"
    assert res[0].arch == "arch"
    assert res[0].distri == "distri"
    assert res[0].version == "version"
    assert res[0].build == "build"
    mock_get_json.assert_called_once_with(
        "api/incident_settings/1", headers={}, params={"type": DEFAULT_SUBMISSION_TYPE}
    )


def test_get_submission_settings_data_error(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = {"error": "foo"}

    res = get_submission_settings_data({}, 1)

    assert len(res) == 0


def test_get_submission_results(mock_get_json: MagicMock, mocker: MockerFixture) -> None:
    mock_get_json.return_value = [{"foo": "bar"}]
    mock_settings = mocker.patch("openqabot.loader.qem.get_submission_settings", return_value=[MagicMock(id=1)])

    res = get_submission_results(1, {})

    assert len(res) == 1
    assert res[0]["foo"] == "bar"
    mock_settings.assert_called_once_with(1, {}, all_submissions=False, submission_type=None)
    mock_get_json.assert_called_once_with("api/jobs/incident/1", headers={})


def test_get_submission_results_error(mock_get_json: MagicMock, mocker: MockerFixture) -> None:
    mock_get_json.return_value = {"error": "foo"}
    mocker.patch("openqabot.loader.qem.get_submission_settings", return_value=[MagicMock(id=1)])

    with pytest.raises(ValueError, match="foo"):
        get_submission_results(1, {})


def test_get_aggregate_settings_no_settings(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = []

    with pytest.raises(NoAggregateResultsError):
        get_aggregate_settings(1, {})

    with pytest.raises(NoAggregateResultsError):
        get_aggregate_settings(1, {}, submission_type=DEFAULT_SUBMISSION_TYPE)


def test_get_aggregate_settings(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = [{"id": 1, "build": "20220101-1"}]

    res = get_aggregate_settings(1, {})

    assert len(res) == 1
    assert res[0].id == 1
    assert res[0].aggregate


def test_get_aggregate_settings_data(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = [{"id": 1, "build": "build"}]
    data = Data(0, "aggregate", 0, "flavor", "arch", "distri", "version", "build", "product")
    res = get_aggregate_settings_data({}, data)

    assert len(res) == 1
    assert res[0].settings_id == 1
    mock_get_json.assert_called_once_with("api/update_settings?product=product&arch=arch", headers={})


def test_get_aggregate_results(mock_get_json: MagicMock, mocker: MockerFixture) -> None:
    mock_get_json.return_value = [{"foo": "bar"}]
    mock_settings = mocker.patch("openqabot.loader.qem.get_aggregate_settings", return_value=[MagicMock(id=1)])

    res = get_aggregate_results(1, {})

    assert len(res) == 1
    assert res[0]["foo"] == "bar"
    mock_settings.assert_called_once_with(1, {}, submission_type=None)
    mock_get_json.assert_called_once_with("api/jobs/update/1", headers={})


def test_get_aggregate_results_error(mock_get_json: MagicMock, mocker: MockerFixture) -> None:
    mock_get_json.return_value = {"error": "foo"}
    mocker.patch("openqabot.loader.qem.get_aggregate_settings", return_value=[MagicMock(id=1)])

    with pytest.raises(ValueError, match="foo"):
        get_aggregate_results(1, {})


def test_get_aggregate_settings_data_none(mock_get_json: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(20)  # INFO
    mock_get_json.return_value = []
    data = Data(0, "aggregate", 0, "flavor", "arch", "distri", "version", "build", "product")
    res = get_aggregate_settings_data({}, data)
    assert res == []
    assert "No aggregate settings found for product product on arch arch" in caplog.text


def test_update_submissions_success(mock_patch: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    mock_patch.return_value.status_code = 200

    res = update_submissions({}, [{}])
    assert res == 0
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "INFO"
    assert "QEM Dashboard submissions updated successfully" in caplog.records[0].message


def test_update_submissions_request_exception(mock_patch: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    mock_patch.side_effect = requests.exceptions.RequestException
    res = update_submissions({}, [{}])
    assert res == 1
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "ERROR"
    assert "QEM Dashboard API request failed" in caplog.records[0].message


def test_update_submissions_unsuccessful_with_error_text(
    mock_patch: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.ERROR)
    mock_patch.return_value.status_code = 500
    mock_patch.return_value.text = "error message"

    res = update_submissions({}, [{}])
    assert res == 2
    assert "QEM Dashboard submission sync failed: Status 500" in caplog.text
    assert "QEM Dashboard error response: error message" in caplog.text


def test_update_submissions_unsuccessful_no_text(mock_patch: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(40)  # ERROR
    mock_patch.return_value.status_code = 500
    mock_patch.return_value.text = ""
    res = update_submissions({}, [{}])
    assert res == 2
    assert "QEM Dashboard submission sync failed: Status 500" in caplog.text
    assert "QEM Dashboard error response" not in caplog.text


def test_post_job_success(mock_put: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    mock_put.return_value.status_code = 200

    post_job({}, {})
    assert "error" not in caplog.text


def test_post_job_unsuccessful(mock_put: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    mock_put.return_value.status_code = 400
    mock_put.return_value.text = "Error message"

    post_job({}, {})
    assert "Error message" in caplog.text


def test_post_job_request_exception(mock_put: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    mock_put.side_effect = requests.exceptions.RequestException
    post_job({}, {})
    assert "QEM Dashboard API request failed" in caplog.text


def test_update_job_success(mock_patch: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    mock_patch.return_value.status_code = 200

    update_job({}, 1, {})
    assert "error" not in caplog.text


def test_update_job_unsuccessful(mock_patch: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    mock_patch.return_value.status_code = 400
    mock_patch.return_value.text = "Error message"
    caplog.set_level(logging.ERROR)

    update_job({}, 1, {})
    assert "Error message" in caplog.text


def test_update_job_request_exception(mock_patch: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    mock_patch.side_effect = requests.exceptions.RequestException
    update_job({}, 1, {})
    assert "QEM Dashboard API request failed" in caplog.text


def test_get_active_submissions_with_type(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = [{"number": 123}]
    res = get_active_submissions({"token": "foo"}, submission_type=DEFAULT_SUBMISSION_TYPE)
    assert res == [123]
    mock_get_json.assert_called_once_with(
        "api/incidents", headers={"token": "foo"}, params={"type": DEFAULT_SUBMISSION_TYPE}
    )


def test_get_active_submissions_no_type(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = [{"number": 123}]
    res = get_active_submissions({"token": "foo"})
    assert res == [123]
    mock_get_json.assert_called_once_with("api/incidents", headers={"token": "foo"}, params={})


def test_get_single_submission_with_type(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = {"number": 123, "rr_number": 456, "type": DEFAULT_SUBMISSION_TYPE}
    res = get_single_submission({"token": "foo"}, 123, submission_type=DEFAULT_SUBMISSION_TYPE)
    assert len(res) == 1
    assert res[0].sub == 123
    mock_get_json.assert_called_once_with(
        "api/incidents/123", headers={"token": "foo"}, params={"type": DEFAULT_SUBMISSION_TYPE}
    )


def test_get_single_submission_no_type(mock_get_json: MagicMock) -> None:
    mock_get_json.return_value = {"number": 123, "rr_number": 456, "type": DEFAULT_SUBMISSION_TYPE}
    res = get_single_submission({"token": "foo"}, 123)
    assert len(res) == 1
    assert res[0].sub == 123
    mock_get_json.assert_called_once_with("api/incidents/123", headers={"token": "foo"}, params={})
