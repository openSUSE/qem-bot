# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader SMELT."""

import re
from unittest.mock import patch

import pytest
import requests
import responses
from jsonschema import ValidationError, validate
from pytest_mock import MockerFixture

from openqabot.loader.smelt import (
    ACTIVE_INC_SCHEMA,
    INCIDENT_SCHEMA,
    get_active_submission_ids,
    get_gitea_update_data,
    get_submission_from_smelt,
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
        res = get_submission_from_smelt(1)

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
        res = get_submission_from_smelt(1)

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
        res = get_submission_from_smelt(1)
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


@responses.activate
def test_get_gitea_update_data_success() -> None:
    """Test get_gitea_update_data with a successful API response."""
    responses.add(
        responses.GET,
        re.compile(r".*/api/experimental/v2/updates/.*"),
        json={"status": "success", "data": {"priority": 366, "is_emergency": True}},
    )
    assert get_gitea_update_data("host", "project", 123) == (366, True)


def test_get_gitea_update_data_failure(caplog: pytest.LogCaptureFixture) -> None:
    """Test get_gitea_update_data with a failing API response."""
    with patch(
        "openqabot.loader.smelt.retried_requests.get", side_effect=requests.exceptions.RequestException("API error")
    ):
        res = get_gitea_update_data("host", "project", 123)
    assert res == (0, False)
    assert "Could not get SMELT v2 update data" in caplog.text
