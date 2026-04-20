# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader Gitea submissions."""

# ruff: noqa: ARG001
import logging
from typing import Any

import pytest
from lxml import etree  # ty: ignore[unresolved-import]
from pytest_mock import MockerFixture

from openqabot.loader import gitea
from openqabot.types.pullrequest import PullRequest


def test_make_submission_from_gitea_pr_dry(mocker: MockerFixture) -> None:
    pr_dict = {
        "number": 124,
        "state": "open",
        "url": "url",
        "base": {"repo": {"full_name": "owner/repo", "name": "repo"}},
    }
    pr = PullRequest.from_json(pr_dict)
    assert pr is not None
    mocker.patch("openqabot.loader.gitea.read_json_file", return_value=[])

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
    pr_dict = {
        "number": 123,
        "state": "open",
        "url": "url",
        "base": {"repo": {"full_name": "owner/repo", "name": "repo"}},
    }
    pr = PullRequest.from_json(pr_dict)
    assert pr is not None
    mocker.patch("openqabot.loader.gitea.iter_gitea_items", return_value=[])

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
    pr_dict = {
        "number": 999,
        "state": "open",
        "url": "url",
        "base": {"repo": {"full_name": "owner/repo", "name": "repo"}},
    }
    pr = PullRequest.from_json(pr_dict)
    assert pr is not None
    mocker.patch("openqabot.loader.gitea.iter_gitea_items", return_value=[])
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
    pr_dict = {
        "number": 123,
        "state": "open",
        "url": "url",
        "base": {"repo": {"full_name": "owner/repo", "name": "repo"}},
    }
    pr = PullRequest.from_json(pr_dict)
    assert pr is not None
    mocker.patch("openqabot.loader.gitea.iter_gitea_items", return_value=[])
    mocker.patch("openqabot.loader.gitea.add_reviews", return_value=0)
    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=False, only_requested_prs=True, dry=False)
    assert res is None
    assert "PR git:123 skipped: No reviews by" in caplog.text


def test_is_review_requested_by_explicit_users() -> None:
    review = {"user": {"login": "user1"}}
    assert gitea.is_review_requested_by(review, users=("user1",))
    assert not gitea.is_review_requested_by(review, users=("user2",))


def test_add_reviews_coverage(mocker: MockerFixture) -> None:
    submission: dict[str, Any] = {}
    reviews = [
        {"dismissed": True, "state": "APPROVED"},
        {"dismissed": False, "state": "PENDING", "user": {"login": "qam-bot"}},
        {"dismissed": False, "state": "APPROVED", "user": {"login": "other"}},
        {"dismissed": False, "state": "REQUEST_REVIEW", "user": {"login": "other"}},
        {"dismissed": False, "state": "COMMENT", "user": {"login": "other"}},
    ]

    def mock_is_req(r: dict[str, Any], users: Any = None) -> bool:
        return r.get("user", {}).get("login") == "qam-bot"

    mocker.patch("openqabot.loader.gitea.is_review_requested_by", side_effect=mock_is_req)

    count = gitea.add_reviews(submission, reviews)
    assert count == 1
    assert submission["inReview"] is True


def test_update_scminfo_coverage(caplog: pytest.LogCaptureFixture) -> None:
    submission = {"number": 123}
    res = etree.fromstring("<root><scminfo></scminfo><scminfo>new</scminfo><scminfo>other</scminfo></root>")
    gitea._update_scminfo(submission, res, "project", "")  # noqa: SLF001
    assert submission["scminfo"] == "new"
    assert "Inconsistent SCM info" in caplog.text

    caplog.clear()
    submission = {"number": 123, "scminfo_prod": "old"}
    res = etree.fromstring("<root><scminfo>new</scminfo></root>")
    gitea._update_scminfo(submission, res, "project", "prod")  # noqa: SLF001
    assert submission["scminfo_prod"] == "old"
    assert "Inconsistent SCM info" in caplog.text


def test_make_submission_from_gitea_pr_no_packages(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    pr_dict = {
        "number": 123,
        "state": "open",
        "url": "url",
        "base": {"repo": {"full_name": "owner/repo", "name": "repo"}},
    }
    pr = PullRequest.from_json(pr_dict)
    assert pr is not None
    # Mocking _fetch_details to return empty lists for reviews, comments, and files
    mocker.patch("openqabot.loader.gitea._fetch_details", return_value=([], [], []))

    # Ensure it skips due to no packages
    def mock_add_chan(inc: dict, *_: Any, **__: Any) -> None:
        inc["channels"].append("chan")

    mocker.patch("openqabot.loader.gitea.add_comments_and_referenced_build_results", side_effect=mock_add_chan)
    # mock add_packages_from_files to do nothing (default)

    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=False, only_requested_prs=False, dry=False)
    assert res is None
    assert "PR git:123 skipped: No packages found" in caplog.text


def test_make_submission_from_gitea_pr_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    """Cover the exception block in make_submission_from_gitea_pr."""
    caplog.set_level(logging.ERROR, logger="bot.loader.gitea")
    pr_dict = {
        "number": 123,
        "state": "open",
        "url": "url",
        "base": {"repo": {"full_name": "owner/repo", "name": "repo"}},
    }
    pr = PullRequest.from_json(pr_dict)
    assert pr is not None
    mocker.patch("openqabot.loader.gitea._fetch_details", side_effect=Exception("API failure"))

    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=False, only_requested_prs=False, dry=False)
    assert res is None
    assert "Gitea API error: Unable to process PR git:123" in caplog.text
