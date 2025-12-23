# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import json
import logging

import pytest
import requests
from pytest_mock import MockerFixture

from openqabot.loader import gitea


def test_post_json_on_not_ok_logs_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger="bot.loader.gitea")
    mocked_post = mocker.Mock()
    mocked_post.ok = False
    mocker.patch("openqabot.loader.gitea.retried_requests.post", return_value=mocked_post)
    gitea.post_json("foo", None, None, host="my.host")
    assert "Gitea API error: POST to my.host/api/v1/foo" in caplog.text


def test_get_open_prs_returns_empty_on_dry_run(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.read_json", return_value=42)
    assert gitea.get_open_prs(None, None, dry=True, number=None) == 42


def test_get_open_prs_returns_specified_pr(mocker: MockerFixture) -> None:
    mocked_get_json = mocker.patch("openqabot.loader.gitea.get_json", return_value=42)
    assert gitea.get_open_prs("my_token", "my_repo", dry=False, number=1) == [42]
    mocked_get_json.assert_called_once_with("repos/my_repo/pulls/1", "my_token")


def test_get_product_version_from_repo_listing(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    mocked_get = mocker.Mock()
    mocked_get.json.side_effect = requests.RequestException
    mocker.patch("openqabot.loader.gitea.retried_requests.get", return_value=mocked_get)
    assert gitea.get_product_version_from_repo_listing("foo:bar", None, None) == ""
    assert "Product version unresolved" in caplog.text


def test_get_product_version_from_repo_listing_request_exception(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.retried_requests.get", side_effect=requests.RequestException("error"))
    res = gitea.get_product_version_from_repo_listing("project", "product", "repo")
    assert res == ""
    assert "Product version unresolved" in caplog.text


def test_get_product_version_from_repo_listing_json_error(mocker: MockerFixture) -> None:
    mock_get = mocker.patch("openqabot.loader.gitea.retried_requests.get")
    mock_get.return_value.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
    res = gitea.get_product_version_from_repo_listing("project", "product", "repo")
    assert res == ""


def test_get_open_prs_empty(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_json", return_value=[])
    res = gitea.get_open_prs("owner", "repo", dry=False, number=None)
    assert res == []


def test_get_open_prs_metadata_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.get_json", side_effect=requests.RequestException("error"))
    res = gitea.get_open_prs("owner", "repo", dry=False, number=124)
    assert res == []
    assert "PR #124 ignored: Could not read PR metadata" in caplog.text


def test_add_build_result_inconsistent_scminfo_is_ignored(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    incident = {"scminfo": "old", "number": 42}
    res = mocker.Mock()
    res.get.return_value = "project"
    mock_scminfo = mocker.Mock()
    mock_scminfo.text = "new"
    res.findall.return_value = [mock_scminfo]
    mocker.patch("openqabot.loader.gitea.add_channel_for_build_result")
    gitea.add_build_result(incident, res, set(), set(), set(), set())
    assert "Inconsistent SCM info" in caplog.text
