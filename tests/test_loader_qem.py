# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from unittest.mock import MagicMock, patch

import pytest

from openqabot.loader.qem import (
    LoaderQemError,
    NoAggregateResultsError,
    NoIncidentResultsError,
    get_active_incidents,
    get_aggregate_settings,
    get_incident_results,
    get_incident_settings,
    get_incident_settings_data,
    get_incidents,
    get_incidents_approver,
    get_single_incident,
)


@patch("openqabot.loader.qem.get_json")
def test_get_incidents_simple(get_json_mock: MagicMock) -> None:
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


@patch("openqabot.loader.qem.get_json")
def test_get_incidents_error(get_json_mock: MagicMock) -> None:
    get_json_mock.return_value = {"error": "some error"}

    with pytest.raises(LoaderQemError):
        get_incidents({})


@patch("openqabot.loader.qem.get_json")
def test_get_incidents_create_none(get_json_mock: MagicMock) -> None:
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

    with patch("openqabot.loader.qem.Incident.create", return_value=None):
        res = get_incidents({})
        assert len(res) == 0


@patch("openqabot.loader.qem.get_json")
def test_get_active_incidents(mock_json: MagicMock) -> None:
    mock_json.return_value = [{"number": 1}, {"number": 2}]

    res = get_active_incidents({})

    assert len(res) == 2
    assert res == [1, 2]


@patch("openqabot.loader.qem.get_json")
def test_get_incidents_approver(mock_json: MagicMock) -> None:
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


@patch("openqabot.loader.qem.get_json")
def test_get_single_incident(mock_json: MagicMock) -> None:
    mock_json.return_value = {"number": 1, "rr_number": 123}

    res = get_single_incident({}, 1)

    assert len(res) == 1
    assert res[0].inc == 1
    assert res[0].req == 123
    mock_json.assert_called_once_with("api/incidents/1", headers={})


@patch("openqabot.loader.qem.get_json")
def test_get_incident_settings_no_settings(mock_json: MagicMock) -> None:
    mock_json.return_value = []

    with pytest.raises(NoIncidentResultsError):
        get_incident_settings(1, {})


@patch("openqabot.loader.qem.get_json")
def test_get_incident_settings_all_incidents(mock_json: MagicMock) -> None:
    mock_json.return_value = [
        {"id": 1, "settings": {"RRID": 1}, "withAggregate": False},
        {"id": 2, "settings": {"RRID": 2}, "withAggregate": False},
    ]

    res = get_incident_settings(1, {}, all_incidents=True)

    assert len(res) == 2
    assert res[0].id == 1
    assert res[1].id == 2


@patch("openqabot.loader.qem.get_json")
def test_get_incident_settings_multiple_rrids(mock_json: MagicMock) -> None:
    mock_json.return_value = [
        {"id": 1, "settings": {"RRID": 1}, "withAggregate": False},
        {"id": 2, "settings": {"RRID": 2}, "withAggregate": False},
        {"id": 3, "settings": {}, "withAggregate": False},
    ]

    res = get_incident_settings(1, {}, all_incidents=False)

    assert len(res) == 2
    assert res[0].id == 2
    assert res[1].id == 3


@patch("openqabot.loader.qem.get_json")
def test_get_incident_settings_no_rrids(mock_json: MagicMock) -> None:
    mock_json.return_value = [
        {"id": 1, "settings": {}, "withAggregate": False},
        {"id": 2, "settings": {}, "withAggregate": False},
    ]

    res = get_incident_settings(1, {}, all_incidents=False)

    assert len(res) == 2


@patch("openqabot.loader.qem.get_json")
def test_get_incident_settings_data(mock_json: MagicMock) -> None:
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


@patch("openqabot.loader.qem.get_json")
def test_get_incident_settings_data_error(mock_json: MagicMock) -> None:
    mock_json.return_value = {"error": "foo"}

    res = get_incident_settings_data({}, 1)

    assert len(res) == 0


@patch("openqabot.loader.qem.get_json")
@patch("openqabot.loader.qem.get_incident_settings")
def test_get_incident_results(mock_settings: MagicMock, mock_json: MagicMock) -> None:
    mock_settings.return_value = [MagicMock(id=1)]
    mock_json.return_value = [{"foo": "bar"}]

    res = get_incident_results(1, {})

    assert len(res) == 1
    assert res[0]["foo"] == "bar"
    mock_settings.assert_called_once_with(1, {}, all_incidents=False)
    mock_json.assert_called_once_with("api/jobs/incident/1", headers={})


@patch("openqabot.loader.qem.get_json")
def test_get_aggregate_settings_no_settings(mock_json: MagicMock) -> None:
    mock_json.return_value = []

    with pytest.raises(NoAggregateResultsError):
        get_aggregate_settings(1, {})


@patch("openqabot.loader.qem.get_json")
def test_get_aggregate_settings(mock_json: MagicMock) -> None:
    mock_json.return_value = [
        {"id": 1, "build": "20220101-1"},
    ]

    res = get_aggregate_settings(1, {})

    assert len(res) == 1
    assert res[0].id == 1
    assert res[0].aggregate
