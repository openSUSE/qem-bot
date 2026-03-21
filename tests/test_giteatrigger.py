# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Tests GiteaTrigger class."""

from argparse import Namespace
from typing import cast
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from openqabot.giteatrigger import GiteaTrigger


@pytest.fixture
def mock_args() -> Namespace:
    """Provide a standard set of CLI arguments for initialization."""
    return Namespace(
        dry=False,
        gitea_token="fake_token",
        gitea_repo="repo/name",
        pr_number=None,
        pr_label="needs-testing",
        # openQA specific args required by OpenQAInterface
        openqa_instance="localhost",
    )


@pytest.fixture
def trigger(mock_args: Namespace, mocker: MockerFixture) -> GiteaTrigger:
    """Initialize GiteaTrigger with mocked external integrations."""
    mocker.patch("openqabot.giteatrigger.OpenQAInterface")

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
            {"number": 1, "labels": [{"name": "needs-testing"}], "base": {"repo": {"name": "r"}, "label": "l"}},
            {"number": 2, "labels": [{"name": "wrong-label"}], "base": {"repo": {"name": "r"}, "label": "l"}},
        ],
    )

    trigger.get_prs_by_label()
    assert len(trigger.prs) == 1
    assert trigger.prs[0].number == 1


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


def test_get_prs_by_label_specific_number(mock_args: Namespace, mocker: MockerFixture) -> None:
    """Cover user provides a specific PR number via CLI."""
    mock_args.pr_number = 1337

    mocker.patch("openqabot.giteatrigger.OpenQAInterface")
    mocker.patch("openqabot.loader.gitea.make_token_header")

    mock_get_pr = mocker.patch(
        "openqabot.giteatrigger.get_open_prs",
        return_value=[
            {"number": 1337, "labels": [{"name": "needs-testing"}], "base": {"repo": {"name": "r"}, "label": "l"}}
        ],
    )

    trigger = GiteaTrigger(mock_args)
    trigger.get_prs_by_label()

    mock_get_pr.assert_called_once()
    assert len(trigger.prs) == 1


def test_get_prs_by_label_loop_exception(trigger: GiteaTrigger, mocker: MockerFixture) -> None:
    """Cover one PR in the list triggers an exception during processing."""
    mocker.patch(
        "openqabot.giteatrigger.get_open_prs",
        return_value=[
            {"number": 1},
            {"number": 2, "labels": [{"name": "needs-testing"}], "base": {"repo": {"name": "r"}, "label": "l"}},
        ],
    )

    trigger.get_prs_by_label()

    assert len(trigger.prs) == 1
    assert trigger.prs[0].number == 2
