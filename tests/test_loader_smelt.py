# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

from jsonschema import ValidationError
from pytest_mock import MockerFixture

from openqabot.loader.smelt import ACTIVE_INC_SCHEMA, INCIDENT_SCHEMA, get_active_incidents, get_incident


def test_get_active_incidents(mocker: MockerFixture) -> None:
    mock_get_json = mocker.patch("openqabot.loader.smelt.get_json")
    mock_get_json.side_effect = [
        {
            "data": {
                "incidents": {
                    "edges": [{"node": {"incidentId": 1}}],
                    "pageInfo": {"hasNextPage": True, "endCursor": "cursor1"},
                }
            }
        },
        {
            "data": {
                "incidents": {
                    "edges": [{"node": {"incidentId": 2}}],
                    "pageInfo": {"hasNextPage": False, "endCursor": "cursor2"},
                }
            }
        },
    ]

    active_incidents = get_active_incidents()
    assert active_incidents == {1, 2}
    assert mock_get_json.call_count == 2


def test_get_active_incidents_validation_error(mocker: MockerFixture) -> None:
    mock_validate = mocker.patch("openqabot.loader.smelt.validate", side_effect=ValidationError("Invalid data"))
    mocker.patch("openqabot.loader.smelt.get_json", return_value={})

    active_incidents = get_active_incidents()
    assert active_incidents == set()
    mock_validate.assert_called_once_with(instance={}, schema=ACTIVE_INC_SCHEMA)


def test_get_incident_successful(mocker: MockerFixture) -> None:
    mock_validate = mocker.patch("openqabot.loader.smelt.validate", return_value=None)
    mock_get_json = mocker.patch("openqabot.loader.smelt.get_json")
    mock_get_json.return_value = {
        "data": {
            "incidents": {
                "edges": [
                    {
                        "node": {
                            "emu": True,
                            "project": "project_name",
                            "repositories": {},
                            "packages": {},
                            "requestSet": {},
                            "crd": "crd_value",
                            "priority": 1,
                        }
                    }
                ]
            }
        }
    }

    result = get_incident(123)
    assert result is not None
    assert result["emu"] is True
    assert result["project"] == "project_name"
    mock_get_json.assert_called_once()
    mock_validate.assert_called_once_with(instance=mock_get_json.return_value, schema=INCIDENT_SCHEMA)


def test_get_incident_validation_error(mocker: MockerFixture) -> None:
    mock_validate = mocker.patch("openqabot.loader.smelt.validate", side_effect=ValidationError("Invalid schema"))
    mock_get_json = mocker.patch("openqabot.loader.smelt.get_json", return_value={})

    result = get_incident(123)
    assert result is None
    mock_get_json.assert_called_once()
    mock_validate.assert_called_once_with(instance={}, schema=INCIDENT_SCHEMA)


def test_get_incident_unknown_error(mocker: MockerFixture) -> None:
    mock_validate = mocker.patch("openqabot.loader.smelt.validate")
    mock_walk = mocker.patch("openqabot.loader.smelt.walk", side_effect=Exception("Unknown error"))
    mock_get_json = mocker.patch("openqabot.loader.smelt.get_json")
    mock_get_json.return_value = {"data": {"incidents": {"edges": [{"node": {"emu": True}}]}}}

    result = get_incident(123)
    assert result is None
    mock_get_json.assert_called_once()
    mock_validate.assert_called_once()
    mock_walk.assert_called_once()
