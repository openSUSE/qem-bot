# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader SMELT."""

from unittest.mock import patch

import pytest
from jsonschema import ValidationError, validate
from pytest_mock import MockerFixture

from openqabot.loader.smelt import (
    ACTIVE_INC_SCHEMA,
    INCIDENT_SCHEMA,
    discover_kind,
    get_active_submission_ids,
    get_submission_from_smelt,
    get_submissions,
)


def test_get_active_submission_ids_simple() -> None:
    fake_data = {
        "data": {
            "incidents": {
                "edges": [{"node": {"incidentId": 1}}, {"node": {"incidentId": 2}}],
                "pageInfo": {"hasNextPage": False, "endCursor": "null"},
            },
        },
    }

    with patch("openqabot.loader.smelt.get_json", return_value=fake_data):
        res = get_active_submission_ids()

    assert res == {1, 2}


def test_get_active_submission_ids_error(caplog: pytest.LogCaptureFixture) -> None:
    fake_data = {"data": {"foo": "bar"}}

    with patch("openqabot.loader.smelt.get_json", return_value=fake_data):
        res = get_active_submission_ids()

    assert res == set()
    assert "SMELT API error: Invalid data structure received for active incidents" in caplog.text


def test_get_submission_from_smelt_simple() -> None:
    fake_data = {
        "data": {
            "incidents": {
                "edges": [
                    {
                        "node": {
                            "emu": True,
                            "project": "project",
                            "repositories": {"edges": []},
                            "packages": {"edges": []},
                            "requestSet": {"edges": []},
                            "crd": None,
                            "priority": 0,
                        },
                    },
                ],
            },
        },
    }

    with patch("openqabot.loader.smelt.get_json", return_value=fake_data):
        res = get_submission_from_smelt(1, "RR")

    assert res == {
        "emu": True,
        "project": "project",
        "repositories": [],
        "packages": [],
        "requestSet": [],
        "crd": None,
        "priority": 0,
    }


def test_get_submission_from_smelt_error(caplog: pytest.LogCaptureFixture) -> None:
    fake_data = {"data": {"foo": "bar"}}

    with patch("openqabot.loader.smelt.get_json", return_value=fake_data):
        res = get_submission_from_smelt(1, "RR")

    assert res is None
    assert "SMELT API error: Invalid data for SMELT incident smelt:1" in caplog.text


def test_get_active_submission_ids_paginated() -> None:
    fake_data_1 = {
        "data": {
            "incidents": {
                "edges": [{"node": {"incidentId": 1}}],
                "pageInfo": {"hasNextPage": True, "endCursor": "cursor"},
            },
        },
    }
    fake_data_2 = {
        "data": {
            "incidents": {
                "edges": [{"node": {"incidentId": 2}}],
                "pageInfo": {"hasNextPage": False, "endCursor": "null"},
            },
        },
    }

    with patch("openqabot.loader.smelt.get_json", side_effect=[fake_data_1, fake_data_2]):
        res = get_active_submission_ids()

    assert res == {1, 2}


def test_get_submission_from_smelt_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch(
        "openqabot.loader.smelt.get_json",
        return_value={"data": {"incidents": {"edges": [{"node": {"emu": True}}]}}},
    )
    with patch("openqabot.loader.smelt.walk", side_effect=Exception("Unexpected error")):
        res = get_submission_from_smelt(1, "RR")
    assert res is None
    assert "SMELT API error: Unexpected error for SMELT incident smelt:1" in caplog.text


def test_active_inc_schema_validation() -> None:
    valid_data = {
        "data": {
            "incidents": {
                "edges": [{"node": {"incidentId": 123}}],
                "pageInfo": {"hasNextPage": False, "endCursor": "xyz"},
            }
        }
    }
    # Should not raise
    validate(instance=valid_data, schema=ACTIVE_INC_SCHEMA)

    invalid_data = {"data": {"incidents": {"edges": []}}}
    with pytest.raises(ValidationError):
        validate(instance=invalid_data, schema=ACTIVE_INC_SCHEMA)


def test_incident_schema_validation() -> None:
    valid_data = {
        "data": {
            "incidents": {
                "edges": [
                    {
                        "node": {
                            "emu": False,
                            "project": "PRJ",
                            "repositories": {},
                            "packages": {},
                            "requestSet": {},
                            "crd": "2023-01-01",
                            "priority": 100,
                        }
                    }
                ]
            }
        }
    }
    # Should not raise
    validate(instance=valid_data, schema=INCIDENT_SCHEMA)


def test_discover_kind_success() -> None:
    with patch("openqabot.loader.smelt.get_json", return_value={}) as mock_get:
        res = discover_kind(1)

    assert res == "RR"
    mock_get.assert_called_once()


def test_discover_kind_retry() -> None:
    # First call returns error, second call success
    with patch("openqabot.loader.smelt.get_json", side_effect=[{"errors": ["foo"]}, {}]) as mock_get:
        res = discover_kind(1)

    assert res == '"RR"'
    assert mock_get.call_count == 2


def test_get_submissions_empty() -> None:
    res = get_submissions(set())
    assert res == []


def test_get_submissions_success() -> None:
    fake_submission = {"foo": "bar"}
    with (
        patch("openqabot.loader.smelt.discover_kind", return_value="RR"),
        patch("openqabot.loader.smelt.get_submission_from_smelt", return_value=fake_submission),
    ):
        res = get_submissions({1, 2})

    assert len(res) == 2
    assert res[0] == fake_submission


def test_discover_kind_fail(caplog: pytest.LogCaptureFixture) -> None:
    with patch("openqabot.loader.smelt.get_json", return_value={"errors": ["foo"]}) as mock_get:
        res = discover_kind(1)

    assert res == "RR"
    assert mock_get.call_count == 2
    assert "Could not discover a valid kind format for SMELT GraphQL API" in caplog.text
