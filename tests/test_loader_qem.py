# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import logging
from unittest.mock import MagicMock

import pytest
import requests
from pytest_mock import MockerFixture

from openqabot.loader.qem import (
    LoaderQemError,
    NoAggregateResultsError,
    NoIncidentResultsError,
    get_active_incidents,
    get_aggregate_results,
    get_aggregate_settings,
    get_aggregate_settings_data,
    get_incident_results,
    get_incident_settings,
    get_incident_settings_data,
    get_incidents,
    get_incidents_approver,
    get_single_incident,
    post_job,
    update_incidents,
    update_job,
)


def test_get_incidents_simple(mocker: MockerFixture) -> None:
    get_json_mock = mocker.patch("openqabot.loader.qem.get_json")
    get_json_mock.return_value = [
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

    res = get_incidents({})

    assert len(res) == 1
    assert res[0].id == 1
    get_json_mock.assert_called_once_with("api/incidents", headers={}, verify=True)


def test_get_incidents_error(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.qem.get_json", return_value={"error": "some error"})
    with pytest.raises(LoaderQemError):
        get_incidents({})


def test_get_incidents_create_none(mocker: MockerFixture) -> None:
    get_json_mock = mocker.patch("openqabot.loader.qem.get_json")
    get_json_mock.return_value = [
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

    mocker.patch("openqabot.loader.qem.Incident.create", return_value=None)
    res = get_incidents({})
    assert len(res) == 0


def test_get_active_incidents(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.qem.get_json", return_value=[{"number": 1}, {"number": 2}])

    res = get_active_incidents({})

    assert len(res) == 2
    assert res == [1, 2]


def test_get_incidents_approver(mocker: MockerFixture) -> None:
    mock_json = mocker.patch("openqabot.loader.qem.get_json")
    mock_json.return_value = [
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

    res = get_incidents_approver({})

    assert len(res) == 1
    assert res[0].inc == 1
    assert res[0].req == 123
    assert res[0].type == "gitea"
    assert res[0].url == "http://foo.bar"
    assert res[0].scm_info == "foo"


def test_get_single_incident(mocker: MockerFixture) -> None:
    mock_json = mocker.patch("openqabot.loader.qem.get_json", return_value={"number": 1, "rr_number": 123})

    res = get_single_incident({}, 1)

    assert len(res) == 1
    assert res[0].inc == 1
    assert res[0].req == 123
    mock_json.assert_called_once_with("api/incidents/1", headers={})


def test_get_incident_settings_no_settings(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.qem.get_json", return_value=[])

    with pytest.raises(NoIncidentResultsError):
        get_incident_settings(1, {})


def test_get_incident_settings_all_incidents(mocker: MockerFixture) -> None:
    mock_json = mocker.patch("openqabot.loader.qem.get_json")
    mock_json.return_value = [
        {"id": 1, "settings": {"RRID": 1}, "withAggregate": False},
        {"id": 2, "settings": {"RRID": 2}, "withAggregate": False},
    ]

    res = get_incident_settings(1, {}, all_incidents=True)

    assert len(res) == 2
    assert res[0].id == 1
    assert res[1].id == 2


def test_get_incident_settings_multiple_rrids(mocker: MockerFixture) -> None:
    mock_json = mocker.patch("openqabot.loader.qem.get_json")
    mock_json.return_value = [
        {"id": 1, "settings": {"RRID": 1}, "withAggregate": False},
        {"id": 2, "settings": {"RRID": 2}, "withAggregate": False},
        {"id": 3, "settings": {}, "withAggregate": False},
    ]

    res = get_incident_settings(1, {}, all_incidents=False)

    assert len(res) == 2
    assert res[0].id == 2
    assert res[1].id == 3


def test_get_incident_settings_no_rrids(mocker: MockerFixture) -> None:
    mock_json = mocker.patch("openqabot.loader.qem.get_json")
    mock_json.return_value = [
        {"id": 1, "settings": {}, "withAggregate": False},
        {"id": 2, "settings": {}, "withAggregate": False},
    ]

    res = get_incident_settings(1, {}, all_incidents=False)

    assert len(res) == 2


def test_get_incident_settings_data(mocker: MockerFixture) -> None:
    mock_json = mocker.patch("openqabot.loader.qem.get_json")
    mock_json.return_value = [
        {
            "id": 1,
            "flavor": "flavor",
            "arch": "arch",
            "settings": {"DISTRI": "distri", "BUILD": "build"},
            "version": "version",
        }
    ]

    res = get_incident_settings_data({}, 1)

    assert len(res) == 1
    assert res[0].incident == 1
    assert res[0].settings_id == 1
    assert res[0].flavor == "flavor"
    assert res[0].arch == "arch"
    assert res[0].distri == "distri"
    assert res[0].version == "version"
    assert res[0].build == "build"
    mock_json.assert_called_once_with("api/incident_settings/1", headers={})


def test_get_incident_settings_data_error(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.qem.get_json", return_value={"error": "foo"})

    res = get_incident_settings_data({}, 1)

    assert len(res) == 0


def test_get_incident_results(mocker: MockerFixture) -> None:
    mock_json = mocker.patch("openqabot.loader.qem.get_json", return_value=[{"foo": "bar"}])
    mock_settings = mocker.patch("openqabot.loader.qem.get_incident_settings", return_value=[MagicMock(id=1)])

    res = get_incident_results(1, {})

    assert len(res) == 1
    assert res[0]["foo"] == "bar"
    mock_settings.assert_called_once_with(1, {}, all_incidents=False)
    mock_json.assert_called_once_with("api/jobs/incident/1", headers={})


def test_get_incident_results_error(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.qem.get_json", return_value={"error": "foo"})
    mocker.patch("openqabot.loader.qem.get_incident_settings", return_value=[MagicMock(id=1)])

    with pytest.raises(ValueError, match="foo"):
        get_incident_results(1, {})


def test_get_aggregate_settings_no_settings(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.qem.get_json", return_value=[])

    with pytest.raises(NoAggregateResultsError):
        get_aggregate_settings(1, {})


def test_get_aggregate_settings(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.qem.get_json", return_value=[{"id": 1, "build": "20220101-1"}])

    res = get_aggregate_settings(1, {})

    assert len(res) == 1
    assert res[0].id == 1
    assert res[0].aggregate


def test_get_aggregate_settings_data(mocker: MockerFixture) -> None:
    mock_json = mocker.patch("openqabot.loader.qem.get_json", return_value=[{"id": 1, "build": "build"}])
    from openqabot.types import Data

    data = Data(0, 0, "flavor", "arch", "distri", "version", "build", "product")
    res = get_aggregate_settings_data({}, data)

    assert len(res) == 1
    assert res[0].settings_id == 1
    mock_json.assert_called_once_with("api/update_settings?product=product&arch=arch", headers={})


def test_get_aggregate_results(mocker: MockerFixture) -> None:
    mock_json = mocker.patch("openqabot.loader.qem.get_json", return_value=[{"foo": "bar"}])
    mock_settings = mocker.patch("openqabot.loader.qem.get_aggregate_settings", return_value=[MagicMock(id=1)])

    res = get_aggregate_results(1, {})

    assert len(res) == 1
    assert res[0]["foo"] == "bar"
    mock_settings.assert_called_once_with(1, {})
    mock_json.assert_called_once_with("api/jobs/update/1", headers={})


def test_get_aggregate_results_error(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.qem.get_json", return_value={"error": "foo"})
    mocker.patch("openqabot.loader.qem.get_aggregate_settings", return_value=[MagicMock(id=1)])

    with pytest.raises(ValueError, match="foo"):
        get_aggregate_results(1, {})


def test_get_aggregate_settings_data_none(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(20)  # INFO
    mocker.patch("openqabot.loader.qem.get_json", return_value=[])
    from openqabot.types import Data

    data = Data(0, 0, "flavor", "arch", "distri", "version", "build", "product")
    res = get_aggregate_settings_data({}, data)
    assert res == []
    assert "No aggregate settings found for product product on arch arch" in caplog.text


def test_update_incidents_success(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mocker.patch("openqabot.loader.qem.patch", return_value=mock_response)

    res = update_incidents({}, [{}])
    assert res == 0
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "INFO"
    assert "QEM Dashboard incidents updated successfully" in caplog.records[0].message


def test_update_incidents_request_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    mocker.patch("openqabot.loader.qem.patch", side_effect=requests.exceptions.RequestException)
    res = update_incidents({}, [{}])
    assert res == 1
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "ERROR"
    assert "QEM Dashboard API request failed" in caplog.records[0].message


def test_update_incidents_unsuccessful_with_error_text(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.text = "error message"
    mocker.patch("openqabot.loader.qem.patch", return_value=mock_response)

    res = update_incidents({}, [{}])
    assert res == 2
    assert "QEM Dashboard incident sync failed: Status 500" in caplog.text
    assert "QEM Dashboard error response: error message" in caplog.text


def test_update_incidents_unsuccessful_no_text(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(40)  # ERROR
    mock_patch = mocker.patch("openqabot.loader.qem.patch")
    mock_patch.return_value.status_code = 500
    mock_patch.return_value.text = ""
    res = update_incidents({}, [{}])
    assert res == 2
    assert "QEM Dashboard incident sync failed: Status 500" in caplog.text
    assert "QEM Dashboard error response" not in caplog.text


def test_post_job_success(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mocker.patch("openqabot.loader.qem.put", return_value=mock_response)

    post_job({}, {})
    assert "error" not in caplog.text


def test_post_job_unsuccessful(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Error message"
    mocker.patch("openqabot.loader.qem.put", return_value=mock_response)

    post_job({}, {})
    assert "Error message" in caplog.text


def test_post_job_request_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    mocker.patch("openqabot.loader.qem.put", side_effect=requests.exceptions.RequestException)
    post_job({}, {})
    assert "QEM Dashboard API request failed" in caplog.text


def test_update_job_success(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mocker.patch("openqabot.loader.qem.patch", return_value=mock_response)

    update_job({}, 1, {})
    assert "error" not in caplog.text


def test_update_job_unsuccessful(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.text = "Error message"
    mocker.patch("openqabot.loader.qem.patch", return_value=mock_response)
    caplog.set_level(logging.ERROR)

    update_job({}, 1, {})
    assert "Error message" in caplog.text


def test_update_job_request_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    mocker.patch("openqabot.loader.qem.patch", side_effect=requests.exceptions.RequestException)
    update_job({}, 1, {})
    assert "QEM Dashboard API request failed" in caplog.text
