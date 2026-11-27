# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test build results referenced in Gitea comments."""

import logging

import pytest
from pytest_mock import MockerFixture

from openqabot.loader import gitea


def test_add_comments_multiple_bot_comments(mocker: MockerFixture) -> None:
    """Reproduce the issue where only the last bot comment is processed.

    If there are two comments, each pointing to a different project,
    both should be picked up.
    """
    submission = {"number": 123, "channels": [], "packages": []}
    comments = [
        {
            "user": {"username": "autogits_obs_staging_bot"},
            "body": "Build started in https://build.suse.de/project/show/PROJ1",
        },
        {
            "user": {"username": "autogits_obs_staging_bot"},
            "body": "Additional builds in https://build.suse.de/project/show/PROJ2",
        },
    ]

    # We want to check if add_build_results is called with BOTH URLs.
    mock_add_build_results = mocker.patch("openqabot.loader.gitea.add_build_results")

    gitea.add_comments_and_referenced_build_results(submission, comments, fake_data=True)

    mock_add_build_results.assert_called_once()
    args, _ = mock_add_build_results.call_args
    # Both URLs should be present and sorted
    assert args[1] == ["https://build.suse.de/project/show/PROJ1", "https://build.suse.de/project/show/PROJ2"]


def test_url_regex_robust() -> None:
    """Verify that regex correctly handles trailing punctuation."""
    body = "Check https://build.suse.de/project/show/PROJ1. (Also https://build.suse.de/project/show/PROJ2)"
    urls = gitea.URL_FINDALL_REGEX.findall(body)

    # New behavior: should NOT include trailing dot or parenthesis
    assert "https://build.suse.de/project/show/PROJ1" in urls
    assert "https://build.suse.de/project/show/PROJ1." not in urls
    assert "https://build.suse.de/project/show/PROJ2" in urls
    assert "https://build.suse.de/project/show/PROJ2)" not in urls


def test_add_comments_no_bot_comments(mocker: MockerFixture) -> None:
    """Verify that nothing happens if no bot comments are found."""
    submission = {"number": 123, "channels": [], "packages": []}
    comments = [{"user": {"username": "someone_else"}, "body": "hello"}]
    mock_add_build_results = mocker.patch("openqabot.loader.gitea.add_build_results")
    gitea.add_comments_and_referenced_build_results(submission, comments, fake_data=True)
    mock_add_build_results.assert_not_called()


def test_add_comments_bot_comments_no_urls(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    """Verify that a warning is logged if bot comments exist but contain no URLs."""
    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    submission = {"number": 123, "project": "owner/repo", "channels": [], "packages": []}
    comments = [{"user": {"username": "autogits_obs_staging_bot"}, "body": "No URLs here"}]
    mock_add_build_results = mocker.patch("openqabot.loader.gitea.add_build_results")
    gitea.add_comments_and_referenced_build_results(submission, comments, fake_data=True)
    mock_add_build_results.assert_not_called()
    assert "PR git:owner/repo:123: No OBS URLs found in comments from autogits_obs_staging_bot" in caplog.text
