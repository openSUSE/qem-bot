# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader Gitea helpers."""

import json
import logging
from unittest.mock import MagicMock

import pytest
import requests
from pytest_mock import MockerFixture

from openqabot.loader import gitea
from openqabot.types.pullrequest import PullRequest


@pytest.fixture
def labeled_pr(mocker: MockerFixture) -> PullRequest:
    mock_pr = mocker.Mock()
    mock_pr.repo_name = "products/sle"
    mock_pr.branch = "main"
    mock_pr.number = 555
    mock_pr.labels = {"label1"}
    return mock_pr


@pytest.fixture
def mocked_response() -> dict[str, str | list]:
    return {
        "StagingProject": "openQA:Staging:A",
        "QA": [{"Name": "SLES", "Label": "label1"}, {"Name": "SLES", "Label": "label2"}],
    }


@pytest.fixture
def mock_get(mocker: MockerFixture, mocked_response: dict[str, str | list]) -> MagicMock:
    mocker.patch("openqabot.config.settings.gitea_url", "https://gitea.com")
    mocker.patch("openqabot.config.settings.obs_download_url", "https://download.obs.com")

    mock_response = mocker.Mock()
    mock_response.json.return_value = mocked_response
    return mocker.patch("openqabot.loader.gitea.retried_requests.get", return_value=mock_response)


def test_post_json_on_not_ok_logs_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger="bot.loader.gitea")
    mocked_post = mocker.Mock()
    mocked_post.ok = False
    mocker.patch("openqabot.loader.gitea.retried_requests.post", return_value=mocked_post)
    gitea.post_json("foo", {}, {}, host="my.host")
    assert "Gitea API error: POST to my.host/api/v1/foo" in caplog.text


def test_patch_json_on_not_ok_logs_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger="bot.loader.gitea")
    mocked_patch = mocker.Mock()
    mocked_patch.ok = False
    mocker.patch("openqabot.loader.gitea.retried_requests.patch", return_value=mocked_patch)
    gitea.patch_json("foo", {}, {}, host="my.host")
    assert "Gitea API error: PATCH to my.host/api/v1/foo" in caplog.text


def test_patch_json_success(mocker: MockerFixture) -> None:
    mocked_patch = mocker.Mock()
    mocked_patch.ok = True
    mocker.patch("openqabot.loader.gitea.retried_requests.patch", return_value=mocked_patch)
    gitea.patch_json("foo", {}, {})


def test_get_product_version_from_repo_listing_json_error(mocker: MockerFixture) -> None:
    mock_log = mocker.patch("openqabot.loader.gitea.log")
    mock_response = MagicMock()
    mock_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
    mocker.patch.object(gitea.retried_requests, "get", return_value=mock_response)
    res = gitea.get_product_version_from_repo_listing("project", "product", "repo")
    assert not res
    assert mock_log.info.called


def test_get_product_version_from_repo_listing_http_error(mocker: MockerFixture) -> None:
    gitea.get_product_version_from_repo_listing.cache_clear()
    mock_log = mocker.patch("openqabot.loader.gitea.log")
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("error")
    mocker.patch.object(gitea.retried_requests, "get", return_value=mock_response)
    res = gitea.get_product_version_from_repo_listing("project", "product", "repo")
    assert not res
    assert mock_log.warning.called


def test_get_product_version_from_repo_listing_request_exception(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    gitea.get_product_version_from_repo_listing.cache_clear()
    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.retried_requests.get", side_effect=requests.RequestException("error"))
    res = gitea.get_product_version_from_repo_listing("project", "product", "repo")
    assert not res
    assert "Product version unresolved" in caplog.text


def test_add_packages_from_patchinfo_non_dry(mocker: MockerFixture) -> None:
    mock_get = mocker.patch("openqabot.loader.gitea.retried_requests.get")
    mock_get.return_value.content = b"<patchinfo><package>pkg1</package></patchinfo>"
    incident = {"packages": []}
    gitea.add_packages_from_patchinfo(incident, {}, "url", dry=False)
    assert incident["packages"] == ["pkg1"]


def test_add_packages_from_patchinfo_parse_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    mock_get = mocker.patch("openqabot.loader.gitea.retried_requests.get")
    mock_get.return_value.content = b"."
    incident = {"packages": []}
    gitea.add_packages_from_patchinfo(incident, {}, "url", dry=False)
    assert incident["packages"] == []
    assert "Failed to parse patchinfo from url: Start tag expected, '<' not found" in caplog.text


def test_get_product_version_from_repo_listing_success(mocker: MockerFixture) -> None:
    gitea.get_product_version_from_repo_listing.cache_clear()
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"name": "SLES-15-SP4-x86_64"},
            {"name": "other-pkg"},
        ]
    }
    mocker.patch("openqabot.loader.gitea.retried_requests.get", return_value=mock_response)
    # product name 'SLES', prefix 'SLES-'
    # _extract_version will be called with name 'SLES-15-SP4-x86_64' and prefix 'SLES-'
    # remainder '15-SP4-x86_64', next(...) returns '15'
    res = gitea.get_product_version_from_repo_listing("project", "SLES", "repo")
    assert res == "15"


def test_get_product_version_from_repo_listing_requests_json_error(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    gitea.get_product_version_from_repo_listing.cache_clear()
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    mock_response = MagicMock()
    # Use a dummy exception that mimics requests.exceptions.JSONDecodeError if needed,
    # but requests.exceptions.JSONDecodeError should work.
    mock_response.json.side_effect = requests.exceptions.JSONDecodeError("msg", "doc", 0)
    mocker.patch("openqabot.loader.gitea.retried_requests.get", return_value=mock_response)
    res = gitea.get_product_version_from_repo_listing("project_json", "product_json", "repo_json")
    assert not res
    assert "Invalid JSON document" in caplog.text


def test_add_channel_for_build_result_local() -> None:
    projects: set[str] = set()
    res = gitea.add_channel_for_build_result("myproj", "local", "myprod", None, projects)
    assert res == "myproj:local"
    assert len(projects) == 0


def test_get_json_success(mocker: MockerFixture) -> None:
    mock_response = mocker.Mock()
    mock_response.json.return_value = {"id": 1}
    mocker.patch("openqabot.loader.gitea.retried_requests.get", return_value=mock_response)
    res = gitea.get_json("some/query", {"Authorization": "token test"})
    assert res == {"id": 1}


def test_iter_gitea_items_success(mocker: MockerFixture) -> None:
    mock_response = mocker.Mock()
    mock_response.json.return_value = [{"id": 1}]
    mock_response.links = {}
    mocker.patch("openqabot.loader.gitea.retried_requests.get", return_value=mock_response)
    res = gitea.iter_gitea_items("some/query", {"Authorization": "token test"})
    assert list(res) == [{"id": 1}]


def test_iter_gitea_items_pagination(mocker: MockerFixture) -> None:
    mock_response1 = mocker.Mock()
    mock_response1.json.return_value = [{"id": 1}]
    mock_response1.links = {"next": {"url": "https://gitea.com/api/v1/some/query?page=2"}}
    mock_response2 = mocker.Mock()
    mock_response2.json.return_value = [{"id": 2}]
    mock_response2.links = {}
    mock_responses = [mock_response1, mock_response2]
    mock_get = mocker.patch("openqabot.loader.gitea.retried_requests.get", side_effect=mock_responses)
    res = gitea.iter_gitea_items("some/query", {"Authorization": "token test"})
    assert list(res) == [{"id": 1}, {"id": 2}]
    assert mock_get.call_count == 2


def test_iter_gitea_items_throws_on_dict(mocker: MockerFixture) -> None:
    mock_response = mocker.Mock()
    mock_response.json.return_value = {"message": "Not Found"}
    mock_response.links = {}
    mocker.patch("openqabot.loader.gitea.retried_requests.get", return_value=mock_response)
    # New behavior: throws TypeError
    with pytest.raises(TypeError, match="Gitea API returned dict instead of list"):
        list(gitea.iter_gitea_items("some/query", {"Authorization": "token test"}))


def test_read_json_file_list_success(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.read_json_file", return_value=[{"id": 1}])
    res = gitea.read_json_file_list("some_file")
    assert res == [{"id": 1}]


def test_read_json_file_list_throws_on_dict(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.read_json_file", return_value={"message": "Not Found"})
    with pytest.raises(TypeError, match="JSON response file 'some_file' returned dict instead of list"):
        gitea.read_json_file_list("some_file")


def test_is_build_acceptable_fail(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    incident = {"failed_or_unpublished_packages": ["pkg1"], "successful_packages": ["pkg2"]}
    assert not gitea.is_build_acceptable_and_log_if_not(incident, 123)
    assert "Skipping PR git:123: Not all packages succeeded or published" in caplog.text


def test_is_build_acceptable_success() -> None:
    incident = {"failed_or_unpublished_packages": [], "successful_packages": ["pkg1"]}
    assert gitea.is_build_acceptable_and_log_if_not(incident, 123)


@pytest.fixture
def mock_review_pr(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("openqabot.loader.gitea.review_pr")


@pytest.fixture
def mock_settings(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("openqabot.loader.gitea.config.settings")


@pytest.mark.parametrize(
    ("bot_user", "api_response", "expected_log", "should_call_review"),
    [
        # Case 1: Already approved via official review
        (
            None,
            [{"commit_id": "sha123", "state": "APPROVED", "user": {"login": "openqa"}}],
            "PR 123 already approved for commit sha123",
            False,
        ),
        # Case 2: Not yet approved (no reviews)
        (None, [], None, True),
        # Case 3: Already approved via bot comment
        (
            "bot",
            [{"body": "@bot: approved\nTested commit: sha123", "user": {"login": "bot"}}],
            "PR 123 already approved via comment for commit sha123",
            False,
        ),
        # Case 4: Comment matches but author is wrong (spoofing attempt)
        (
            "bot",
            [{"body": "@bot: approved\nTested commit: sha123", "user": {"login": "imposter"}}],
            None,
            True,
        ),
        # Case 5: Already approved via bot comment using obs_group name
        (
            "bot-review",
            [{"body": "@bot-review: approved\nTested commit: sha123", "user": {"login": "openqa"}}],
            "PR 123 already approved via comment for commit sha123",
            False,
        ),
        # Case 6: No bot comments found
        ("bot", [], None, True),
    ],
)
def test_approve_pr_scenarios(
    *,
    mock_review_pr: MagicMock,
    mock_settings: MagicMock,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    bot_user: str | None,
    api_response: list[dict],
    expected_log: str | None,
    should_call_review: bool,
) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.iter_gitea_items", return_value=api_response)

    mock_settings.obs_group = "openqa"
    mock_settings.git_review_bot_user = bot_user

    res = gitea.approve_pr({}, "repo", 123, "sha123", "msg")

    assert res is True
    if expected_log:
        assert expected_log in caplog.text
    if should_call_review:
        mock_review_pr.assert_called_once_with({}, "repo", 123, "msg", "sha123", approve=True)
    else:
        mock_review_pr.assert_not_called()


def test_review_url() -> None:
    """Verify review_url construction."""
    assert gitea.review_url("repo", 123, 456) == "repos/repo/pulls/123/reviews/456"


def test_commit_status_url() -> None:
    """Verify commit_status_url construction."""
    pr = PullRequest(
        number=123,
        state="open",
        project="test-project",
        branch="main",
        url="http://url",
        commit_sha="sha123",
        raw_labels=[],
    )
    assert gitea.commit_status_url(pr) == "repos/test-project/statuses/sha123"


def test_get_events_by_timeline(mocker: MockerFixture) -> None:
    """Verify get_events_by_timeline logic including push event reset and duplicate events."""
    # Scenario 1: Multiple events including duplicates and pull_push break
    mock_events = [
        {"type": "comment", "user": {"login": "user3"}},  # Not reached
        {"type": "pull_push", "user": {"login": "user1"}},  # Loop break
        {"type": "review", "user": {"login": "user2"}},  # New user
        {"type": "review", "user": {"login": "user1"}},  # New event type for same user
        {"type": "comment", "user": {"login": "user1"}},  # Duplicate event type for same user
        {"type": "comment", "user": {"login": "user1"}},
    ]
    mock_iter = mocker.patch("openqabot.loader.gitea.iter_gitea_items", return_value=mock_events)

    events = gitea.get_events_by_timeline({}, "repo", 123)

    assert "user1" in events
    assert "comment" in events["user1"]
    assert "review" in events["user1"]
    assert "user2" in events
    assert "review" in events["user2"]
    assert "user3" not in events
    assert mock_iter.call_count == 1

    # Scenario 2: Empty timeline
    mocker.patch("openqabot.loader.gitea.iter_gitea_items", return_value=[])
    events = gitea.get_events_by_timeline({}, "repo", 456)
    assert events == {}


def test_approve_pr_exception(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mocker.patch("openqabot.loader.gitea.iter_gitea_items", side_effect=Exception("API fail"))
    caplog.set_level(logging.ERROR, logger="bot.loader.gitea")

    res = gitea.approve_pr({}, "repo", 123, "sha123", "msg")

    assert res is False
    assert "Gitea API error: Failed to approve PR 123" in caplog.text
