# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader Gitea PRs."""

import json

import pytest
import requests
from pytest_mock import MockerFixture

from openqabot.loader import gitea
from openqabot.types.pullrequest import PullRequest


def test_get_open_prs_returns_specified_pr(mocker: MockerFixture) -> None:
    pr_data = {
        "number": 1,
        "state": "open",
        "labels": [],
        "base": {"repo": {"full_name": "my_repo"}},
    }
    mocked_get_json = mocker.patch("openqabot.loader.gitea.get_json", return_value=pr_data)
    res = gitea.get_open_prs({"Authorization": "token my_token"}, "my_repo", number=1)
    assert len(res) == 1
    assert isinstance(res[0], PullRequest)
    assert res[0].number == 1
    mocked_get_json.assert_called_once_with("repos/my_repo/pulls/1", {"Authorization": "token my_token"})


def test_get_open_prs_returns_empty_list_on_invalid_pr(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_json", return_value={"invalid": "data"})
    res = gitea.get_open_prs({}, "my_repo", number=1)
    assert res == []


def test_get_open_prs_iter_pages(mocker: MockerFixture) -> None:
    pr_data = [
        {"number": 1, "state": "open", "base": {"repo": {"full_name": "repo"}}},
        {"number": 2, "state": "open", "base": {"repo": {"full_name": "repo"}}},
    ]
    mocker.patch("openqabot.loader.gitea.iter_gitea_items", return_value=pr_data)
    res = gitea.get_open_prs({}, "repo", number=None)
    assert len(res) == 2
    assert all(isinstance(pr, PullRequest) for pr in res)
    assert [pr.number for pr in res] == [1, 2]


def test_get_open_prs_single_request_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_json", side_effect=requests.exceptions.RequestException("Request failed"))
    res = gitea.get_open_prs({}, "my_repo", number=1)
    assert res == []
    assert "PR git:1 ignored: Request failed" in caplog.text


def test_get_open_prs_iter_request_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch(
        "openqabot.loader.gitea.iter_gitea_items", side_effect=requests.exceptions.RequestException("Iter failed")
    )
    res = gitea.get_open_prs({}, "repo", number=None)
    assert res == []
    assert "Gitea API error: Could not fetch open PRs from repo" in caplog.text


def test_get_open_prs_iter_json_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch("openqabot.loader.gitea.iter_gitea_items", side_effect=json.JSONDecodeError("JSON error", "doc", 0))
    res = gitea.get_open_prs({}, "repo", number=None)
    assert res == []
    assert "Gitea API error: Could not fetch open PRs from repo" in caplog.text
