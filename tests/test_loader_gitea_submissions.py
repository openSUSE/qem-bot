# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader Gitea submissions."""

# ruff: noqa: ARG001
import logging
from typing import Any

import pytest
from pytest_mock import MockerFixture

from openqabot.loader import gitea


def test_make_submission_from_gitea_pr_dry(mocker: MockerFixture) -> None:
    pr = {"number": 124, "state": "open", "url": "url", "base": {"repo": {"full_name": "owner/repo", "name": "repo"}}}
    mocker.patch("openqabot.loader.gitea.read_json", return_value=[])

    def mock_add_comments(incident: dict, _comments: list, *, dry: bool) -> None:
        incident["channels"] = [1]

    mocker.patch("openqabot.loader.gitea.add_comments_and_referenced_build_results", side_effect=mock_add_comments)

    def mock_add_packages(incident: dict, _token: dict, _files: list, *, dry: bool) -> None:
        incident["packages"] = ["pkg"]

    mocker.patch("openqabot.loader.gitea.add_packages_from_files", side_effect=mock_add_packages)

    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=False, only_requested_prs=False, dry=True)
    assert res is not None


def test_make_submission_from_gitea_pr_skips(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    pr = {"number": 123, "state": "open", "url": "url", "base": {"repo": {"full_name": "owner/repo", "name": "repo"}}}
    mocker.patch("openqabot.loader.gitea.get_json", return_value=[])

    # Skip due to no channels
    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=False, only_requested_prs=False, dry=False)
    assert res is None
    assert "PR git:123 skipped: No channels found" in caplog.text

    # Skip due to build not acceptable
    caplog.clear()
    mocker.patch("openqabot.loader.gitea.is_build_acceptable_and_log_if_not", return_value=False)

    def mock_add_comments(incident: dict, _comments: list, *, dry: bool) -> None:
        incident["channels"] = [1]

    mocker.patch("openqabot.loader.gitea.add_comments_and_referenced_build_results", side_effect=mock_add_comments)
    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=True, only_requested_prs=False, dry=False)
    assert res is None

    # Skip due to no packages
    caplog.clear()
    mocker.patch("openqabot.loader.gitea.is_build_acceptable_and_log_if_not", return_value=True)
    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=False, only_requested_prs=False, dry=False)
    assert res is None
    assert "PR git:123 skipped: No packages found" in caplog.text


def test_make_submission_from_gitea_pr_dry_other_number_passes(mocker: MockerFixture) -> None:
    pr = {"number": 999, "state": "open", "url": "url", "base": {"repo": {"full_name": "owner/repo", "name": "repo"}}}
    mocker.patch("openqabot.loader.gitea.add_reviews", return_value=1)

    def mock_add_chan(inc: dict, *_: Any, **__: Any) -> None:
        inc["channels"].append("chan")

    mocker.patch("openqabot.loader.gitea.add_comments_and_referenced_build_results", side_effect=mock_add_chan)

    def mock_add_pkg(inc: dict, *_: Any, **__: Any) -> None:
        inc["packages"].append("pkg")

    mocker.patch("openqabot.loader.gitea.add_packages_from_files", side_effect=mock_add_pkg)

    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=False, only_requested_prs=False, dry=True)
    assert res is not None
    assert res["number"] == 999


def test_make_submission_from_gitea_pr_no_reviews(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    pr = {"number": 123, "state": "open", "url": "url", "base": {"repo": {"full_name": "owner/repo", "name": "repo"}}}
    mocker.patch("openqabot.loader.gitea.get_json", return_value=[])
    mocker.patch("openqabot.loader.gitea.add_reviews", return_value=0)
    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=False, only_requested_prs=True, dry=False)
    assert res is None
    assert "PR git:123 skipped: No reviews by" in caplog.text


def test_make_submission_from_gitea_pr_exception(caplog: pytest.LogCaptureFixture) -> None:
    pr = {"number": 123}  # Missing base/repo
    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=False, only_requested_prs=False, dry=False)
    assert res is None
    assert "Gitea API error: Unable to process PR git:123" in caplog.text


def test_is_review_requested_by_explicit_users() -> None:
    review = {"user": {"login": "user1"}}
    assert gitea.is_review_requested_by(review, users=("user1",))
    assert not gitea.is_review_requested_by(review, users=("user2",))
