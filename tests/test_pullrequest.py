# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test PullRequest class."""

import json

import pytest
import requests
from pytest_mock import MockerFixture

from openqabot.types.pullrequest import PullRequest


def test_pull_request_has_labels() -> None:
    """Verify that has_labels returns True only when all labels are present."""
    raw_data = [{"name": "bug", "id": 1}, {"name": "urgent", "id": 2}, {"name": "v1.0", "id": 3}]
    pr = PullRequest(
        number=124,
        state="open",
        project="os-autoinst",
        branch="master",
        url="http://gitea/pull/124",
        commit_sha="abcd123",
        raw_labels=raw_data,
    )

    assert pr.has_all_labels({"bug", "urgent"})
    assert pr.has_all_labels({"v1.0"})
    assert not pr.has_all_labels({"bug", "missing"})
    assert not pr.has_all_labels({"feature"})


def test_pull_request_id_property() -> None:
    """Verify that id property returns the same value as number."""
    pr = PullRequest(
        number=124,
        state="open",
        project="os-autoinst",
        branch="master",
        url="http://gitea/pull/124",
        commit_sha="abcd123",
        raw_labels=[],
    )
    assert pr.id == 124


def test_create_from_json_invalid_data(caplog: pytest.LogCaptureFixture) -> None:
    """Verify create_from_json returns None and logs error on invalid data."""
    # Missing 'number'
    assert PullRequest.from_json({"base": {"repo": {"full_name": "repo"}}}) is None
    assert "PR git:? ignored: Could not read PR metadata" in caplog.text

    # Missing 'base'
    caplog.clear()
    assert PullRequest.from_json({"number": 123}) is None
    assert "PR git:123 ignored: Could not read PR metadata" in caplog.text


def test_from_json_request_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    """Verify from_json returns None and logs error on RequestException."""
    mocker.patch("openqabot.types.pullrequest.PullRequest", side_effect=requests.exceptions.RequestException)
    assert PullRequest.from_json({"number": 123}) is None
    assert "PR git:123 ignored: Could not read PR metadata" in caplog.text


def test_from_json_json_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    """Verify from_json returns None and logs error on JSONDecodeError."""
    # JSONDecodeError needs a few arguments for its constructor
    mocker.patch("openqabot.types.pullrequest.PullRequest", side_effect=json.JSONDecodeError("msg", "doc", 0))
    assert PullRequest.from_json({"number": 123}) is None
    assert "PR git:123 ignored: Could not read PR metadata" in caplog.text
