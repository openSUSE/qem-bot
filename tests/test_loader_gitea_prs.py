# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import pytest
import requests
from pytest_mock import MockerFixture

from openqabot.loader import gitea


def test_get_open_prs_returns_empty_on_dry_run(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.read_json", return_value=42)
    assert gitea.get_open_prs({}, "repo", dry=True, number=None) == 42


def test_get_open_prs_returns_specified_pr(mocker: MockerFixture) -> None:
    mocked_get_json = mocker.patch("openqabot.loader.gitea.get_json", return_value=42)
    assert gitea.get_open_prs({"Authorization": "token my_token"}, "my_repo", dry=False, number=1) == [42]
    mocked_get_json.assert_called_once_with("repos/my_repo/pulls/1", {"Authorization": "token my_token"})


def test_get_open_prs_metadata_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.get_json", side_effect=requests.RequestException("error"))
    res = gitea.get_open_prs({}, "repo", dry=False, number=124)
    assert res == []
    assert "PR git:124 ignored: Could not read PR metadata" in caplog.text


def test_get_open_prs_iter_pages(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_json", side_effect=[[1], [2], []])
    res = gitea.get_open_prs({}, "repo", dry=False, number=None)
    assert res == [1, 2]


def test_get_open_prs_json_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    caplog.set_level(logging.ERROR, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.get_json", side_effect=requests.exceptions.JSONDecodeError("msg", "doc", 0))
    res = gitea.get_open_prs({}, "repo", dry=False, number=None)
    assert res == []
    assert "Gitea API error: Invalid JSON received for open PRs" in caplog.text


def test_get_open_prs_request_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    caplog.set_level(logging.ERROR, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.get_json", side_effect=requests.exceptions.RequestException("error"))
    res = gitea.get_open_prs({}, "repo", dry=False, number=None)
    assert res == []
    assert "Gitea API error: Could not fetch open PRs" in caplog.text
