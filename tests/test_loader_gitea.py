# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import pytest
from pytest_mock import MockerFixture

from openqabot.loader.gitea import get_open_prs, post_json


def test_post_json_on_not_ok_logs_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocked_post = mocker.Mock()
    mocked_post.ok = False
    mocker.patch("openqabot.loader.gitea.retried_requests.post", return_value=mocked_post)
    post_json("foo", None, None, host="my.host")
    assert "Unable to POST my.host/api/v1/foo" in caplog.text


def test_get_open_prs_returns_empty_on_dry_run(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.read_json", return_value=42)
    assert get_open_prs(None, None, dry=True, number=None) == 42


def test_get_open_prs_returns_specified_pr(mocker: MockerFixture) -> None:
    mocked_get_json = mocker.patch("openqabot.loader.gitea.get_json", return_value=42)
    assert get_open_prs("my_token", "my_repo", dry=False, number=1) == [42]
    mocked_get_json.assert_called_once_with("repos/my_repo/pulls/1", "my_token")
