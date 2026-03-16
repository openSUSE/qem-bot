# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test PullRequest class."""

import logging

import pytest
import requests
from pytest_mock import MockerFixture

from openqabot.loader import gitea
from openqabot.types.pullrequest import PullRequest


def test_get_open_prs_specific_number_json_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    """Cover JSONDecodeError when fetching a specific PR number."""
    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.get_json", side_effect=requests.exceptions.JSONDecodeError("msg", "doc", 0))
    res = gitea.get_open_prs({}, "repo", fake_data=False, number=124)

    assert res == []
    assert "PR git:124 ignored: Could not read PR metadata" in caplog.text


def test_get_open_prs_specific_number_key_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    """Cover KeyError (simulating unexpected API response structure)."""
    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.get_json", side_effect=KeyError("missing_field"))

    res = gitea.get_open_prs({}, "repo", fake_data=False, number=124)

    assert res == []
    assert "PR git:124 ignored: Could not read PR metadata" in caplog.text


def test_pull_request_has_labels() -> None:
    """Verify that has_labels returns True only when all labels are present."""
    raw_data = [{"name": "bug", "id": 1}, {"name": "urgent", "id": 2}, {"name": "v1.0", "id": 3}]
    pr = PullRequest(number=124, repo_name="os-autoinst", branch="master", raw_labels=raw_data)

    assert pr.has_labels({"bug", "urgent"})
    assert pr.has_labels({"v1.0"})
    assert not pr.has_labels({"bug", "missing"})
    assert not pr.has_labels({"feature"})
