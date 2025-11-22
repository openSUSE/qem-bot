# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from unittest.mock import MagicMock, patch

from jsonschema import ValidationError

from openqabot.loader.smelt import ACTIVE_INC_SCHEMA, INCIDENT_SCHEMA, get_active_incidents, get_incident


@patch("openqabot.loader.smelt.get_json")
def test_get_active_incidents(mock_get_json: MagicMock) -> None:
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


@patch("openqabot.loader.smelt.validate")
@patch("openqabot.loader.smelt.get_json")
def test_get_active_incidents_validation_error(mock_get_json: MagicMock, mock_validate: MagicMock) -> None:
    mock_validate.side_effect = ValidationError("Invalid data")
    mock_get_json.return_value = {}

    active_incidents = get_active_incidents()
    assert active_incidents == set()
    mock_validate.assert_called_once_with(instance={}, schema=ACTIVE_INC_SCHEMA)


@patch("openqabot.loader.smelt.validate")
@patch("openqabot.loader.smelt.get_json")
def test_get_incident_successful(mock_get_json: MagicMock, mock_validate: MagicMock) -> None:
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
    mock_validate.return_value = None

    result = get_incident(123)
    assert result is not None
    assert result["emu"] is True
    assert result["project"] == "project_name"
    mock_get_json.assert_called_once()
    mock_validate.assert_called_once_with(instance=mock_get_json.return_value, schema=INCIDENT_SCHEMA)


@patch("openqabot.loader.smelt.validate")
@patch("openqabot.loader.smelt.get_json")
def test_get_incident_validation_error(mock_get_json: MagicMock, mock_validate: MagicMock) -> None:
    mock_get_json.return_value = {}
    mock_validate.side_effect = ValidationError("Invalid schema")

    result = get_incident(123)
    assert result is None
    mock_get_json.assert_called_once()
    mock_validate.assert_called_once_with(instance={}, schema=INCIDENT_SCHEMA)


@patch("openqabot.loader.smelt.validate")
@patch("openqabot.loader.smelt.walk")
@patch("openqabot.loader.smelt.get_json")
def test_get_incident_unknown_error(mock_get_json: MagicMock, mock_walk: MagicMock, mock_validate: MagicMock) -> None:
    mock_get_json.return_value = {"data": {"incidents": {"edges": [{"node": {"emu": True}}]}}}
    mock_walk.side_effect = Exception("Unknown error")

    result = get_incident(123)
    assert result is None
    mock_get_json.assert_called_once()
    mock_validate.assert_called_once()
    mock_walk.assert_called_once()
