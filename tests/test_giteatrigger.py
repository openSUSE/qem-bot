# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Tests GiteaTrigger class."""

import logging
from argparse import Namespace
from typing import cast
from unittest.mock import MagicMock
from urllib.parse import urlparse

import pytest
from pytest_mock import MockerFixture

from openqabot.giteatrigger import GiteaTrigger
from openqabot.types.types import Data


@pytest.fixture
def mock_args() -> Namespace:
    """Provide a standard set of CLI arguments for initialization."""
    return Namespace(
        dry=False,
        gitea_token="fake_token",
        gitea_repo="repo/name",
        pr_number=None,
        pr_label="needs-testing",
        token="dashboard_token",
        # openQA specific args required by OpenQAInterface
        openqa_instance=urlparse("https://localhost"),
    )


@pytest.fixture
def _fake_get_gitea_staging_config(mocker: MockerFixture) -> None:
    mocker.patch(
        "openqabot.giteatrigger.get_gitea_staging_config",
        return_value={
            "StagingProject": "S:SL:M:PullRequest",
            "QA": [
                {"Name": "SLES", "Label": "qalabel1"},
                {"Name": "SLES-2", "Label": "qalabel2"},
                {"Name": "SLES-3", "Label": "qalabel3"},
            ],
        },
    )


@pytest.fixture
def trigger(mock_args: Namespace, mocker: MockerFixture, _fake_get_gitea_staging_config: MockerFixture) -> GiteaTrigger:
    """Initialize GiteaTrigger with mocked external integrations."""
    mocker.patch("openqabot.giteatrigger.OpenQAInterface")
    mocker.patch("openqabot.giteatrigger.Commenter")

    mocker.patch("osc.conf.get_config")
    mocker.patch("openqabot.loader.gitea.make_token_header", return_value={"Authorization": "token x"})

    return GiteaTrigger(mock_args)


def test_check_pullrequest_triggers_job(trigger: GiteaTrigger, mocker: MockerFixture) -> None:
    """Verifies that post_job is called with correct parameters."""
    mock_match = MagicMock()
    mock_match.group.side_effect = lambda x: {
        0: "SLES-15.5-Online-x86_64-Build1.1.install.iso",
        "product": "SLES",
        "version": "15.5",
        "arch": "x86_64",
        "build": "1.1",
    }[x]

    mock_crawler = mocker.patch("openqabot.giteatrigger.Crawler")
    mock_crawler.return_value.get_regex_match_from_url.return_value = mock_match

    mocker.patch("openqabot.giteatrigger.generate_repo_url", return_value="http://fake.url/")
    mocker.patch.object(trigger, "is_openqa_triggering_needed", return_value=True)
    mock_pr = MagicMock(number=123)
    trigger.check_pullrequest(mock_pr)

    cast("MagicMock", trigger.openqa.post_job).assert_called_once()
    args, _ = cast("MagicMock", trigger.openqa.post_job).call_args
    settings = args[0]
    assert settings["FLAVOR"] == "Online-Staging"
    assert settings["VERSION"] == "15.5:PR-123"
    assert settings["BUILD"] == "PR-123-1.1:SLES-15.5"
    assert settings["ISO_URL"] == "http://fake.url//SLES-15.5-Online-x86_64-Build1.1.install.iso"


def test_is_openqatriggering_needed_false(trigger: GiteaTrigger, mocker: MockerFixture) -> None:
    """Verifies that post_job is not called when openQA triggering is already satisfied."""
    mock_match = MagicMock()
    mock_match.group.side_effect = lambda x: {
        0: "iso_name",
        "product": "SLES",
        "version": "15.5",
        "arch": "x86_64",
        "build": "1.1",
    }[x]

    mocker.patch("openqabot.giteatrigger.Crawler").return_value.get_regex_match_from_url.return_value = mock_match

    mocker.patch("openqabot.giteatrigger.generate_repo_url", return_value="http://fake.url/")
    mocker.patch.object(trigger, "is_openqa_triggering_needed", return_value=False)
    trigger.check_pullrequest(MagicMock(number=123))

    cast("MagicMock", trigger.openqa.post_job).assert_not_called()


def test_get_prs_by_label_filtering(trigger: GiteaTrigger, mocker: MockerFixture) -> None:
    """Tests that only PRs with the correct label are added."""
    mocker.patch(
        "openqabot.giteatrigger.get_open_prs",
        return_value=[
            {
                "number": 1,
                "labels": [{"name": "needs-testing"}, {"name": "qalabel1"}],
                "base": {"repo": {"name": "r", "full_name": "owner/r"}, "label": "l"},
                "html_url": "u",
                "head": {"sha": "xyz"},
            },
            {
                "number": 2,
                "labels": [{"name": "wrong-label"}, {"name": "qalabel1"}],
                "base": {"repo": {"name": "r", "full_name": "owner/r"}, "label": "l"},
                "html_url": "u",
                "head": {"sha": "xyz"},
            },
            {
                "number": 3,
                "labels": [{"name": "needs-testing"}],
                "base": {"repo": {"name": "r", "full_name": "owner/r"}, "label": "l"},
                "html_url": "u",
                "head": {"sha": "xyz"},
            },
        ],
    )

    trigger.get_prs_by_label()
    assert len(trigger.prs) == 1
    assert trigger.prs[0].number == 1
    assert trigger.prs[0].repo_name == "owner/r"


def test_check_pullrequest_dry_run(trigger: GiteaTrigger, mocker: MockerFixture) -> None:
    """Verifies that post_job is NOT called during a dry run."""
    trigger.dry = True
    mock_match = MagicMock()
    mock_match.group.side_effect = lambda x: {
        0: "iso",
        "product": "SLES",
        "version": "15",
        "arch": "x86_64",
        "build": "1",
    }[x]

    mock_crawler = mocker.patch("openqabot.giteatrigger.Crawler")
    mock_crawler.return_value.get_regex_match_from_url.return_value = mock_match
    mocker.patch("openqabot.giteatrigger.generate_repo_url", return_value="http://fake.url/")
    mock_pr = MagicMock(number=456)
    trigger.check_pullrequest(mock_pr)
    cast("MagicMock", trigger.openqa.openqa.openqa_request).assert_not_called()


def test_check_pullrequest_no_iso_found(trigger: GiteaTrigger, mocker: MockerFixture) -> None:
    """Cover when Crawler finds no matching ISO."""
    mock_crawler = mocker.patch("openqabot.giteatrigger.Crawler")
    mock_crawler.return_value.get_regex_match_from_url.return_value = None
    mocker.patch("openqabot.giteatrigger.generate_repo_url", return_value="http://fake.url/")

    mock_pr = MagicMock(number=789)
    trigger.check_pullrequest(mock_pr)

    cast("MagicMock", trigger.openqa.post_job).assert_not_called()


def test_get_prs_by_label_api_exception(trigger: GiteaTrigger, mocker: MockerFixture) -> None:
    """Cover when the Gitea API itself raises an Exception."""
    mocker.patch("openqabot.giteatrigger.get_open_prs", side_effect=Exception("API Down"))

    with pytest.raises(Exception, match="API Down"):
        trigger.get_prs_by_label()


def test_trigger_call_execution(trigger: GiteaTrigger, mocker: MockerFixture) -> None:
    """Cover  __call__ method logic."""
    mock_get = mocker.patch.object(trigger, "get_prs_by_label")
    mock_check = mocker.patch.object(trigger, "check_pullrequest")
    mock_pr = MagicMock()
    trigger.prs = [mock_pr]
    result = trigger()
    assert result == 0
    mock_get.assert_called_once()
    mock_check.assert_called_once_with(mock_pr)


@pytest.mark.usefixtures("_fake_get_gitea_staging_config")
def test_get_prs_by_label_specific_number(mock_args: Namespace, mocker: MockerFixture) -> None:
    """Cover user provides a specific PR number via CLI."""
    mock_args.pr_number = 1337

    mocker.patch("openqabot.giteatrigger.OpenQAInterface")
    mocker.patch("openqabot.loader.gitea.make_token_header")

    mock_get_pr = mocker.patch(
        "openqabot.giteatrigger.get_open_prs",
        return_value=[
            {
                "number": 1337,
                "labels": [{"name": "needs-testing"}, {"name": "qalabel1"}],
                "base": {"repo": {"name": "r", "full_name": "owner/r"}, "label": "l"},
                "html_url": "u",
                "head": {"sha": "xyz"},
            }
        ],
    )

    trigger = GiteaTrigger(mock_args)
    trigger.get_prs_by_label()

    mock_get_pr.assert_called_once()
    assert len(trigger.prs) == 1
    assert trigger.prs[0].repo_name == "owner/r"


def test_check_pullrequest_comments_when_no_trigger_needed(trigger: GiteaTrigger, mocker: MockerFixture) -> None:
    """Verifies that comment_on_pr is called when no trigger is needed and comment is True."""
    trigger.comment = True
    mock_match = MagicMock()
    mock_match.group.side_effect = lambda x: {
        0: "iso",
        "product": "SLES",
        "version": "15",
        "arch": "x86_64",
        "build": "1",
    }[x]

    mocker.patch("openqabot.giteatrigger.Crawler").return_value.get_regex_match_from_url.return_value = mock_match
    mocker.patch("openqabot.giteatrigger.generate_repo_url", return_value="http://fake.url/")
    mocker.patch.object(trigger, "is_openqa_triggering_needed", return_value=False)
    mock_comment_on_pr = mocker.patch.object(trigger, "comment_on_pr")

    mock_pr = MagicMock(number=123)
    trigger.check_pullrequest(mock_pr)

    mock_comment_on_pr.assert_called_once()


def test_comment_on_pr_build_injection(trigger: GiteaTrigger, mocker: MockerFixture) -> None:
    """Tests that the build string is injected into raw openQA jobs."""
    mock_approve_pr = mocker.patch("openqabot.giteatrigger.approve_pr")
    mock_jobs = [{"id": 1, "state": "done", "result": "passed"}]
    cast("MagicMock", trigger.openqa.get_jobs).return_value = mock_jobs
    cast("MagicMock", trigger.commenter.generate_comment).return_value = ("Summary", "passed")

    mock_pr = MagicMock(number=123, url="http://fake.url/123", commit_sha="sha123", repo_name="fake_repo")
    trigger.comment_on_pr(mock_pr, "product", "version", "arch", "PR-BUILD")

    assert mock_jobs[0]["build"] == "PR-BUILD"
    cast("MagicMock", trigger.commenter.generate_comment).assert_called_once_with(mock_pr, mock_jobs)
    mock_approve_pr.assert_called_once_with(trigger.gitea_token, "fake_repo", 123, "sha123", mocker.ANY)


def test_comment_on_pr_dry_run_approves(
    trigger: GiteaTrigger, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """Tests that approve_pr is not called during a dry run."""
    caplog.set_level(logging.INFO)
    trigger.dry = True
    mock_approve_pr = mocker.patch("openqabot.giteatrigger.approve_pr")
    mock_jobs = [{"id": 1, "state": "done", "result": "passed"}]
    cast("MagicMock", trigger.openqa.get_jobs).return_value = mock_jobs
    cast("MagicMock", trigger.commenter.generate_comment).return_value = ("Summary", "passed")

    mock_pr = MagicMock(number=123, url="http://fake.url/123", commit_sha="sha123", repo_name="fake_repo")
    trigger.comment_on_pr(mock_pr, "product", "version", "arch", "PR-BUILD")

    mock_approve_pr.assert_not_called()
    assert "Dry run: Would approve PR 123" in caplog.text


def test_comment_on_pr_no_jobs(trigger: GiteaTrigger) -> None:
    """Tests comment_on_pr when no jobs are found."""
    cast("MagicMock", trigger.openqa.get_jobs).return_value = []
    cast("MagicMock", trigger.commenter.generate_comment).return_value = None

    mock_pr = MagicMock(number=123)
    trigger.comment_on_pr(mock_pr, "product", "version", "arch", "build")

    cast("MagicMock", trigger.commenter.gitea_comment).assert_not_called()


def test_comment_on_pr_exception(trigger: GiteaTrigger) -> None:
    """Tests comment_on_pr when fetching jobs fails."""
    cast("MagicMock", trigger.openqa.get_jobs).side_effect = Exception("openQA Down")

    mock_pr = MagicMock(number=123)
    trigger.comment_on_pr(mock_pr, "product", "version", "arch", "build")

    cast("MagicMock", trigger.commenter.gitea_comment).assert_not_called()


def test_get_prs_by_label_exception_during_pr_processing(
    trigger: GiteaTrigger, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """Tests get_prs_by_label when an exception occurs while processing a PR."""
    mocker.patch(
        "openqabot.giteatrigger.get_open_prs",
        return_value=[{"number": 1}],  # Missing required fields to trigger exception
    )
    trigger.get_prs_by_label()
    assert len(trigger.prs) == 0
    assert "Unable to process PR git:1" in caplog.text


def test_check_pullrequest_no_matched_iso(trigger: GiteaTrigger, mocker: MockerFixture) -> None:
    """Tests check_pullrequest when no ISO is matched."""
    mocker.patch("openqabot.giteatrigger.Crawler").return_value.get_regex_match_from_url.return_value = None
    mocker.patch("openqabot.giteatrigger.generate_repo_url", return_value="http://fake.url/")

    mock_pr = MagicMock(number=123)
    trigger.check_pullrequest(mock_pr)
    # Should log warning but not crash


def test_comment_on_pr_data_creation(trigger: GiteaTrigger) -> None:
    """Tests the Data object creation in comment_on_pr."""
    mock_get_jobs = cast("MagicMock", trigger.openqa.get_jobs)
    mock_get_jobs.return_value = []

    mock_pr = MagicMock(number=123)
    trigger.comment_on_pr(mock_pr, "product", "version", "arch", "build")

    mock_get_jobs.assert_called_once()
    data = mock_get_jobs.call_args[0][0]
    assert isinstance(data, Data)
    assert data.submission == 123
    assert data.submission_type == "git"


def test_is_openqa_triggering_needed_with_results(trigger: GiteaTrigger) -> None:
    """Tests is_openqa_triggering_needed when results are found."""
    cast("MagicMock", trigger.openqa.get_scheduled_product_stats).return_value = {"job": "done"}
    assert trigger.is_openqa_triggering_needed("v", "a", "b") is False
