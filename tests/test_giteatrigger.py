# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Tests GiteaTrigger class."""

import logging
from argparse import Namespace
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock
from urllib.parse import urlparse

import pytest
import requests
from openqa_client.exceptions import RequestError
from pytest_mock import MockerFixture

from openqabot import config
from openqabot.commenter import Commenter
from openqabot.errors import NoResultsError
from openqabot.giteatrigger import GiteaTrigger
from openqabot.loader.triggerconfig import TriggerConfig
from openqabot.types.pullrequest import PullRequest
from openqabot.types.types import Data


@pytest.fixture
def mock_trigger_config() -> TriggerConfig:
    """Provide a standard TriggerConfig for tests."""
    return TriggerConfig(distri="sle", flavor="Online-Staging")


@pytest.fixture
def mock_args() -> Namespace:
    """Provide a standard set of CLI arguments for initialization."""
    return Namespace(
        dry=False,
        gitea_token="fake_token",
        gitea_project="repo/name",
        pr_number=None,
        pr_label="needs-testing",
        token="dashboard_token",
        # openQA specific args required by OpenQAInterface
        openqa_instance=urlparse("https://localhost"),
        configs=Path("/fake/path"),
        maintenance=False,
    )


@pytest.fixture
def _fake_get_configs_from_path(mocker: MockerFixture, mock_trigger_config: TriggerConfig) -> None:
    mocker.patch(
        "openqabot.giteatrigger.get_configs_from_path",
        return_value=[mock_trigger_config],
    )


def _make_pr(number: int | None, trigger_config: TriggerConfig, **kwargs: Any) -> MagicMock:
    """Create a mocked PullRequest bound to a trigger config."""
    pr = MagicMock(number=number, **kwargs)
    pr.project = trigger_config.project
    pr.branch = trigger_config.branch
    return pr


@pytest.fixture
def trigger(
    mock_args: Namespace,
    mocker: MockerFixture,
    _fake_get_configs_from_path: None,
) -> GiteaTrigger:
    """Initialize GiteaTrigger with mocked external integrations."""
    mocker.patch("openqabot.giteatrigger.OpenQAInterface")
    mocker.patch("openqabot.giteatrigger.Commenter")

    mocker.patch("osc.conf.get_config")
    mocker.patch("openqabot.loader.gitea.make_token_header", return_value={"Authorization": "token x"})

    return GiteaTrigger(mock_args)


def test_check_pullrequest_triggers_job(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
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

    mocker.patch("openqabot.loader.triggerconfig.TriggerConfig.generate_obs_repo_url", return_value="http://fake.url/")
    mocker.patch.object(trigger, "is_openqa_triggering_needed", return_value=True)
    mock_pr = _make_pr(123, mock_trigger_config)
    trigger.check_pullrequest(mock_pr)

    cast("MagicMock", trigger.openqa.post_job).assert_called_once()
    args, _ = cast("MagicMock", trigger.openqa.post_job).call_args
    settings = args[0]
    assert settings["FLAVOR"] == "Online-Staging"
    assert settings["VERSION"] == "15.5:PR-123"
    assert settings["BUILD"] == "PR-123-1.1:SLES-15.5"
    assert settings["ISO_1_URL"] == "http://fake.url//SLES-15.5-Online-x86_64-Build1.1.install.iso"
    assert settings["ISO_1"] == "SLES-15.5-Online-x86_64-Build1.1.install.iso"


def test_check_pullrequest_with_image_regex(trigger: GiteaTrigger, mocker: MockerFixture) -> None:
    """Verifies that HDD parameters are used when image_regex is configured and image is found."""
    # Create a trigger config with image_regex
    trigger_config_with_image = TriggerConfig(
        distri="sle",
        flavor="Minimal-VM-Cloud-Staging-dev",
        image_regex=r"SLES-[\d\.]+-Minimal-VM\.(?P<arch>\w+)-Cloud-Build[0-9\.]+\.qcow2",
    )

    # Mock ISO match
    mock_iso_match = MagicMock()
    mock_iso_match.group.side_effect = lambda x: {
        0: "SLES-16.1-Online-x86_64-Build2.1.install.iso",
        "product": "SLES",
        "version": "16.1",
        "arch": "x86_64",
        "build": "2.1",
    }[x]

    # Mock image match
    mock_image_match = MagicMock()
    mock_image_match.group.side_effect = lambda x: {
        0: "SLES-16.1-Minimal-VM.x86_64-Cloud-Build2.1.qcow2",
    }.get(x, "SLES-16.1-Minimal-VM.x86_64-Cloud-Build2.1.qcow2")

    # Mock Crawler to return different matches based on URL
    mock_crawler = mocker.patch("openqabot.giteatrigger.Crawler")
    mock_crawler.return_value.get_regex_match_from_url.side_effect = lambda url, _: (
        mock_image_match if "/images" in url else mock_iso_match
    )

    mocker.patch(
        "openqabot.loader.triggerconfig.TriggerConfig.generate_obs_repo_url", return_value="http://fake.url/product/iso"
    )
    mocker.patch.object(trigger, "is_openqa_triggering_needed", return_value=True)
    trigger.config_list = [trigger_config_with_image]
    mock_pr = _make_pr(456, trigger_config_with_image)
    trigger.check_pullrequest(mock_pr)

    cast("MagicMock", trigger.openqa.post_job).assert_called_once()
    args, _ = cast("MagicMock", trigger.openqa.post_job).call_args
    settings = args[0]

    # Verify HDD parameters are set
    assert settings["HDD_1_URL"] == "http://fake.url/images/SLES-16.1-Minimal-VM.x86_64-Cloud-Build2.1.qcow2"
    assert settings["HDD_1"] == "SLES-16.1-Minimal-VM.x86_64-Cloud-Build2.1.qcow2"

    # Verify ISO parameters are NOT set
    assert "ISO_1_URL" not in settings
    assert "ISO_1" not in settings

    # Verify common parameters are still set
    assert settings["FLAVOR"] == "Minimal-VM-Cloud-Staging-dev"
    assert settings["VERSION"] == "16.1:PR-456"
    assert settings["BUILD"] == "PR-456-2.1:SLES-16.1"


def test_check_pullrequest_with_image_regex_not_found(
    trigger: GiteaTrigger, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """Verifies warning is logged when image_regex is configured but no matching image is found."""
    trigger_config_with_image = TriggerConfig(
        distri="sle",
        flavor="Minimal-VM-Cloud-Staging-dev",
        image_regex=r"SLES-[\d\.]+-Minimal-VM\.(?P<arch>\w+)-Cloud-Build[0-9\.]+\.qcow2",
    )

    # Mock ISO match
    mock_iso_match = MagicMock()
    mock_iso_match.group.side_effect = lambda x: {
        0: "SLES-16.1-Online-x86_64-Build2.1.install.iso",
        "product": "SLES",
        "version": "16.1",
        "arch": "x86_64",
        "build": "2.1",
    }[x]

    # Mock Crawler to return ISO match but None for image
    mock_crawler = mocker.patch("openqabot.giteatrigger.Crawler")
    mock_crawler.return_value.get_regex_match_from_url.side_effect = lambda url, _: (
        None if "/images" in url else mock_iso_match
    )

    mocker.patch(
        "openqabot.loader.triggerconfig.TriggerConfig.generate_obs_repo_url", return_value="http://fake.url/product/iso"
    )
    mocker.patch.object(trigger, "is_openqa_triggering_needed", return_value=True)
    trigger.config_list = [trigger_config_with_image]
    mock_pr = _make_pr(789, trigger_config_with_image)
    trigger.check_pullrequest(mock_pr)

    # Verify warning was logged
    assert "No image found matching regex" in caplog.text

    # Verify post_job was still called (without HDD or ISO parameters)
    cast("MagicMock", trigger.openqa.post_job).assert_called_once()
    args, _ = cast("MagicMock", trigger.openqa.post_job).call_args
    settings = args[0]

    # Verify HDD parameters are not set but ISO parameters are fallback
    assert "HDD_1_URL" not in settings
    assert "HDD_1" not in settings
    assert settings["ISO_1_URL"] == "http://fake.url/product/iso/SLES-16.1-Online-x86_64-Build2.1.install.iso"
    assert settings["ISO_1"] == "SLES-16.1-Online-x86_64-Build2.1.install.iso"


def test_is_openqatriggering_needed_false(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
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

    mocker.patch("openqabot.loader.triggerconfig.TriggerConfig.generate_obs_repo_url", return_value="http://fake.url/")
    mocker.patch.object(trigger, "is_openqa_triggering_needed", return_value=False)
    mock_pr = _make_pr(123, mock_trigger_config)
    trigger.check_pullrequest(mock_pr)

    cast("MagicMock", trigger.openqa.post_job).assert_not_called()


def test_load_prs_for_project(trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig) -> None:
    """Tests that open PRs are loaded into the prs dictionary."""
    mocker.patch(
        "openqabot.giteatrigger.get_open_prs",
        return_value=[
            PullRequest.from_json({
                "number": 1,
                "labels": [{"name": "needs-testing"}, {"name": "qalabel1"}],
                "base": {"repo": {"name": "r", "full_name": "owner/r"}, "label": "l"},
                "html_url": "u",
                "head": {"sha": "xyz"},
                "state": "open",
            }),
            PullRequest.from_json({
                "number": 2,
                "labels": [{"name": "wrong-label"}, {"name": "qalabel1"}],
                "base": {"repo": {"name": "r", "full_name": "owner/r"}, "label": "l"},
                "html_url": "u",
                "head": {"sha": "xyz"},
                "state": "open",
            }),
            PullRequest.from_json({
                "number": 3,
                "labels": [{"name": "needs-testing"}],
                "base": {"repo": {"name": "r", "full_name": "owner/r"}, "label": "l"},
                "html_url": "u",
                "head": {"sha": "xyz"},
                "state": "open",
            }),
        ],
    )

    trigger.load_prs_for_project(mock_trigger_config.project)
    assert len(trigger.prs[mock_trigger_config.project]) == 3
    assert trigger.prs[mock_trigger_config.project][0].number == 1
    assert trigger.prs[mock_trigger_config.project][0].project == "owner/r"


def test_check_pullrequest_dry_run(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
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
    mocker.patch("openqabot.loader.triggerconfig.TriggerConfig.generate_obs_repo_url", return_value="http://fake.url/")
    mock_pr = _make_pr(456, mock_trigger_config)
    trigger.check_pullrequest(mock_pr)
    cast("MagicMock", trigger.openqa.openqa.openqa_request).assert_not_called()


def test_check_pullrequest_no_iso_found(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
    """Cover when Crawler finds no matching ISO."""
    mock_crawler = mocker.patch("openqabot.giteatrigger.Crawler")
    mock_crawler.return_value.get_regex_match_from_url.return_value = None
    mocker.patch("openqabot.loader.triggerconfig.TriggerConfig.generate_obs_repo_url", return_value="http://fake.url/")

    mock_pr = _make_pr(789, mock_trigger_config)
    trigger.check_pullrequest(mock_pr)

    cast("MagicMock", trigger.openqa.post_job).assert_not_called()


def test_get_prs_by_label_api_exception(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
    """Cover when the Gitea API itself raises an Exception."""
    mocker.patch("openqabot.giteatrigger.get_open_prs", side_effect=Exception("API Down"))

    with pytest.raises(Exception, match="API Down"):
        trigger.load_prs_for_project(mock_trigger_config.project)


def test_trigger_call_execution(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
    """Cover  __call__ method logic."""
    mock_load = mocker.patch.object(trigger, "load_prs_for_project")
    mock_check = mocker.patch.object(trigger, "check_pullrequest")
    mock_pr = MagicMock()
    trigger.prs = {mock_trigger_config.project: [mock_pr]}
    # Ensure config_list is not empty so check_pullrequest is called
    trigger.config_list = [mock_trigger_config]
    result = trigger()
    assert result == 0
    mock_load.assert_called_once_with(mock_trigger_config.project)
    mock_check.assert_called_once_with(mock_pr)


def test_trigger_call_execution_duplicate_prs(trigger: GiteaTrigger, mocker: MockerFixture) -> None:
    """Cover __call__ duplicate PR filtering logic."""
    mocker.patch.object(trigger, "load_prs_for_project")
    mock_check = mocker.patch.object(trigger, "check_pullrequest")
    mock_pr = MagicMock()
    mock_pr.number = 123

    config1 = TriggerConfig(distri="sle", flavor="Online-Staging")
    config2 = TriggerConfig(distri="sle", flavor="Other-Staging")
    config1.project = "SLFO"
    config2.project = "SLFO"
    trigger.prs = {"SLFO": [mock_pr]}
    trigger.config_list = [config1, config2]

    result = trigger()
    assert result == 0
    mock_check.assert_called_once_with(mock_pr)


def test_check_pullrequest_mixed_trigger_and_covered_skips_comment(
    trigger: GiteaTrigger, mocker: MockerFixture
) -> None:
    """When any flavor is (re)triggered, no approval/comment happens even if others are covered."""
    trigger.comment = True
    config_trigger = TriggerConfig(distri="sle", flavor="A")
    config_covered = TriggerConfig(distri="sle", flavor="B")
    config_trigger.project = config_covered.project = "SLFO"
    trigger.config_list = [config_trigger, config_covered]
    mock_iso = MagicMock(arch="x86_64", build="b", flavor="A")
    mocker.patch.object(trigger, "_should_skip_pr", return_value=False)
    mocker.patch.object(trigger, "_get_matched_iso", return_value=(mock_iso, "iso"))
    mocker.patch.object(trigger, "is_openqa_triggering_needed", side_effect=[True, False])
    mock_comment = mocker.patch.object(trigger, "comment_on_pr")
    mock_pr = _make_pr(1, config_trigger)
    trigger.check_pullrequest(mock_pr)
    mock_comment.assert_not_called()


@pytest.mark.usefixtures("_fake_get_configs_from_path")
def test_get_prs_by_label_specific_number(
    mock_args: Namespace, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
    """Cover user provides a specific PR number via CLI."""
    mock_args.pr_number = 1337

    mocker.patch("openqabot.giteatrigger.OpenQAInterface")
    mocker.patch("openqabot.loader.gitea.make_token_header")

    mock_get_pr = mocker.patch(
        "openqabot.giteatrigger.get_open_prs",
        return_value=[
            PullRequest.from_json({
                "number": 1337,
                "labels": [{"name": "needs-testing"}, {"name": "qalabel1"}],
                "base": {"repo": {"name": "r", "full_name": "owner/r"}, "label": "l"},
                "html_url": "u",
                "head": {"sha": "xyz"},
            })
        ],
    )

    trigger = GiteaTrigger(mock_args)
    trigger.load_prs_for_project(mock_trigger_config.project)

    mock_get_pr.assert_called_once()
    assert len(trigger.prs[mock_trigger_config.project]) == 1
    assert trigger.prs[mock_trigger_config.project][0].project == "owner/r"


def test_check_pullrequest_comments_when_no_trigger_needed(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
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
    mocker.patch("openqabot.loader.triggerconfig.TriggerConfig.generate_obs_repo_url", return_value="http://fake.url/")
    mocker.patch.object(trigger, "is_openqa_triggering_needed", return_value=False)
    mock_comment_on_pr = mocker.patch.object(trigger, "comment_on_pr")

    mock_pr = _make_pr(123, mock_trigger_config)
    trigger.check_pullrequest(mock_pr)

    mock_comment_on_pr.assert_called_once()


def test_comment_on_pr_build_injection(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
    """Tests that the build string is injected into raw openQA jobs."""
    mock_approve_pr = mocker.patch("openqabot.giteatrigger.approve_pr")
    mock_jobs = [{"id": 1, "state": "done", "result": "passed"}]
    cast("MagicMock", trigger.openqa.get_jobs).return_value = mock_jobs
    cast("MagicMock", trigger.commenter.generate_comment).return_value = ("Summary", "passed")

    mock_pr = MagicMock(number=123, url="http://fake.url/123", commit_sha="sha123", project="fake_repo")
    mock_iso = MagicMock()
    mock_iso.product = "product"
    mock_iso.version = "version"
    mock_iso.arch = "arch"
    mock_iso.build = "PR-BUILD"
    data = Data.from_trigger_config_and_matched_iso(mock_trigger_config, mock_iso, mock_pr.number)
    trigger.comment_on_pr(mock_pr, [data])

    passed_jobs = cast("MagicMock", trigger.commenter.generate_comment).call_args[0][1]
    assert passed_jobs[0]["build"] == "PR-BUILD"
    mock_approve_pr.assert_called_once_with(trigger.gitea_token, "fake_repo", 123, "sha123", mocker.ANY)


def test_comment_on_pr_one_flavor_fails_blocks_approval(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_args: Namespace
) -> None:
    """A failing flavor must block approval even when another flavor passes."""
    mocker.patch("openqabot.config.settings.enable_detailed_comments", new=False)
    mock_approve_pr = mocker.patch("openqabot.giteatrigger.approve_pr")
    commenter = Commenter(mock_args, submissions=[])
    commenter.client.openqa.baseurl = "https://openqa"
    mock_gitea_comment = mocker.patch.object(commenter, "gitea_comment")
    trigger.commenter = commenter

    jobs_by_flavor = {
        "A": [{"id": 1, "state": "done", "result": "passed", "build": "b"}],
        "B": [{"id": 2, "state": "done", "result": "failed", "build": "b"}],
    }
    cast("MagicMock", trigger.openqa.get_jobs).side_effect = lambda data: jobs_by_flavor[data.flavor]

    data_list = [Data(1, "git", 0, flavor, "x86_64", "sle", "15", "b", "product") for flavor in jobs_by_flavor]
    trigger.comment_on_pr(MagicMock(number=1, url="http://host/o/r/pulls/1"), data_list)

    assert mock_gitea_comment.call_args[0][2] == "failed"
    mock_approve_pr.assert_not_called()


def test_comment_on_pr_dry_run_approves(
    trigger: GiteaTrigger,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    mock_trigger_config: TriggerConfig,
) -> None:
    """Tests that approve_pr is not called during a dry run."""
    caplog.set_level(logging.INFO)
    trigger.dry = True
    mock_approve_pr = mocker.patch("openqabot.giteatrigger.approve_pr")
    mock_jobs = [{"id": 1, "state": "done", "result": "passed"}]
    cast("MagicMock", trigger.openqa.get_jobs).return_value = mock_jobs
    cast("MagicMock", trigger.commenter.generate_comment).return_value = ("Summary", "passed")

    mock_pr = MagicMock(number=123, url="http://fake.url/123", commit_sha="sha123", repo_name="fake_repo")
    mock_iso = MagicMock()
    mock_iso.product = "product"
    mock_iso.version = "version"
    mock_iso.arch = "arch"
    mock_iso.build = "PR-BUILD"
    data = Data.from_trigger_config_and_matched_iso(mock_trigger_config, mock_iso, mock_pr.number)
    trigger.comment_on_pr(mock_pr, [data])

    mock_approve_pr.assert_not_called()
    assert "Dry run: Would approve PR 123" in caplog.text


def test_comment_on_pr_no_jobs(trigger: GiteaTrigger, mock_trigger_config: TriggerConfig) -> None:
    """Tests comment_on_pr when no jobs are found."""
    cast("MagicMock", trigger.openqa.get_jobs).return_value = []
    cast("MagicMock", trigger.commenter.generate_comment).return_value = None

    mock_pr = MagicMock(number=123)
    mock_iso = MagicMock()
    data = Data.from_trigger_config_and_matched_iso(mock_trigger_config, mock_iso, mock_pr.number)
    trigger.comment_on_pr(mock_pr, [data])

    cast("MagicMock", trigger.commenter.gitea_comment).assert_not_called()


def test_check_pullrequest_no_matched_iso(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
    """Tests check_pullrequest when no ISO is matched."""
    mocker.patch("openqabot.giteatrigger.Crawler").return_value.get_regex_match_from_url.return_value = None
    mocker.patch("openqabot.loader.triggerconfig.TriggerConfig.generate_obs_repo_url", return_value="http://fake.url/")

    mock_pr = _make_pr(123, mock_trigger_config)
    trigger.check_pullrequest(mock_pr)
    # Should log warning but not crash


def test_comment_on_pr_data_creation(trigger: GiteaTrigger, mock_trigger_config: TriggerConfig) -> None:
    """Tests the Data object creation in comment_on_pr."""
    mock_get_jobs = cast("MagicMock", trigger.openqa.get_jobs)
    mock_get_jobs.return_value = []

    mock_pr = MagicMock(number=123)
    mock_iso = MagicMock()
    mock_iso.product = "product"
    mock_iso.version = "version"
    mock_iso.arch = "arch"
    mock_iso.build = "build"
    data = Data.from_trigger_config_and_matched_iso(mock_trigger_config, mock_iso, mock_pr.number)
    trigger.comment_on_pr(mock_pr, [data])

    mock_get_jobs.assert_called_once()
    data = mock_get_jobs.call_args[0][0]
    assert isinstance(data, Data)
    assert data.submission == 123
    assert data.submission_type == "git"
    assert data.flavor == mock_trigger_config.flavor
    assert data.distri == mock_trigger_config.distri


def test_should_skip_pr(trigger: GiteaTrigger, mock_trigger_config: TriggerConfig, mocker: MockerFixture) -> None:
    """Tests branch and label-based skipping of pull requests."""
    # Scenario 1: PR has required labels
    pr_ok = MagicMock(spec=PullRequest)
    pr_ok.branch = "slfo-main"
    pr_ok.has_all_labels.return_value = True
    assert trigger._should_skip_pr(pr_ok, mock_trigger_config) is False  # noqa: SLF001

    # Scenario 2: PR is missing required labels
    pr_skip = MagicMock(spec=PullRequest)
    pr_skip.branch = "slfo-main"
    pr_skip.has_all_labels.return_value = False
    pr_skip.number = 123
    pr_skip.labels = {"label1"}
    assert trigger._should_skip_pr(pr_skip, mock_trigger_config) is True  # noqa: SLF001

    # Scenario 3: opensuse (o3) mode
    trigger.is_maintenance = True
    mock_trigger_config.branch = "master"
    pr_o3 = MagicMock(spec=PullRequest)
    pr_o3.branch = "master"
    pr_o3.number = 123
    mocker.patch.object(trigger, "is_build_finished", return_value=True)
    assert trigger._should_skip_pr(pr_o3, mock_trigger_config) is False  # noqa: SLF001

    mocker.patch.object(trigger, "is_build_finished", return_value=False)
    assert trigger._should_skip_pr(pr_o3, mock_trigger_config) is True  # noqa: SLF001

    pr_o3.branch = "wrong-branch"
    assert trigger._should_skip_pr(pr_o3, mock_trigger_config) is True  # noqa: SLF001


def test_check_pullrequest_opensuse_success(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
    """Tests the full opensuse PR check, trigger and approval path."""
    trigger.is_maintenance = True
    mock_trigger_config.branch = "openSUSE-Leap-15.5"
    mock_trigger_config.project = "openSUSE_Leap_15.5"
    mock_trigger_config.repo_template = "{repo_prefix}/"
    mock_trigger_config.settings = {"OS_TEST_TEMPLATE": "test-template"}

    mock_pr = _make_pr(123, mock_trigger_config, spec=PullRequest, commit_sha="sha123", url="http://fake-pr-url")
    mock_pr.generate_webhook_id.return_value = "gitea:pr:123"

    mocker.patch.object(trigger, "is_build_finished", return_value=True)
    mocker.patch.object(trigger.repodiff, "get_staged_update_name", return_value="staged-package")
    mocker.patch.object(trigger, "is_openqa_triggering_needed", return_value=True)
    mock_approve = mocker.patch("openqabot.giteatrigger.gitea.approve_pr")

    trigger.check_pullrequest(mock_pr)

    # Verify openQA post_job was called
    cast("MagicMock", trigger.openqa.post_job).assert_called_once()
    args, _ = cast("MagicMock", trigger.openqa.post_job).call_args
    settings = args[0]

    # Verify opensuse-specific settings
    assert settings["INCIDENT_REPO"] == "http://download.suse.de/ibs/"
    assert settings["OS_TEST_TEMPLATE"] == "test-template"
    assert settings["GITEA_STATUSES_URL"] == "repos/openSUSE_Leap_15.5/statuses/sha123"
    assert settings["webhook_id"] == "gitea:pr:123"

    # Verify gitea approval was not called (it's called during comment stage instead)
    mock_approve.assert_not_called()


def test_check_pullrequest_opensuse_no_staged_update(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
    """Tests opensuse PR check when get_staged_update_name raises NoResultsError."""
    trigger.is_maintenance = True
    mock_trigger_config.branch = "openSUSE-Leap-15.5"
    mock_trigger_config.repo_template = "{repo_prefix}/"

    mock_pr = _make_pr(123, mock_trigger_config, spec=PullRequest)

    mocker.patch.object(trigger, "is_build_finished", return_value=True)
    mocker.patch.object(trigger.repodiff, "get_staged_update_name", side_effect=NoResultsError("error"))
    mock_log = mocker.patch("openqabot.giteatrigger.log.warning")

    trigger.check_pullrequest(mock_pr)

    # Verify warning log and early exit
    mock_log.assert_called_once_with("No staged update name found for PR 123 in http://download.suse.de/ibs/")
    cast("MagicMock", trigger.openqa.post_job).assert_not_called()


def test_load_prs_for_project_already_loaded(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
    """Tests that projects are only loaded once."""
    mock_get = mocker.patch("openqabot.giteatrigger.get_open_prs", return_value=[])
    trigger.prs[mock_trigger_config.project] = []
    trigger.load_prs_for_project(mock_trigger_config.project)
    mock_get.assert_not_called()


def test_check_pullrequest_skipped(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
    """Tests that check_pullrequest returns early if PR can be skipped."""
    mock_pr = _make_pr(None, mock_trigger_config, spec=PullRequest)
    mocker.patch.object(trigger, "_should_skip_pr", return_value=True)
    mock_log = mocker.patch("openqabot.giteatrigger.log.info")

    trigger.check_pullrequest(mock_pr)
    mock_log.assert_not_called()


def test_is_build_finished_no_events(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
    """Tests is_build_finished when no events are found."""
    mocker.patch("openqabot.loader.gitea.get_events_by_timeline", return_value={})
    mock_pr = MagicMock(number=123)
    assert trigger.is_build_finished(mock_pr, mock_trigger_config) is False


def test_is_build_finished_no_bot_comment(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
    """Tests is_build_finished when bot user hasn't commented."""
    mocker.patch("openqabot.loader.gitea.get_events_by_timeline", return_value={"other_user": {}})
    mock_pr = MagicMock(number=123)
    assert trigger.is_build_finished(mock_pr, mock_trigger_config) is False


def test_is_build_finished_states(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
    """Tests various build states in is_build_finished."""
    events = {config.settings.git_review_bot_user: {"review": {"review_id": 456}}}
    mocker.patch("openqabot.loader.gitea.get_events_by_timeline", return_value=events)
    mock_pr = MagicMock(number=123)

    # State: APPROVED, Body: Build successful
    mocker.patch(
        "openqabot.giteatrigger.gitea.get_json", return_value={"state": "APPROVED", "body": "Build successful"}
    )
    assert trigger.is_build_finished(mock_pr, mock_trigger_config) is True

    # State: APPROVED, Body: No package changes...
    mocker.patch(
        "openqabot.giteatrigger.gitea.get_json",
        return_value={
            "state": "APPROVED",
            "body": "No package changes, not rebuilding project by default, accepting change",
        },
    )
    assert trigger.is_build_finished(mock_pr, mock_trigger_config) is False

    # State: APPROVED, Body: Unknown
    mocker.patch("openqabot.giteatrigger.gitea.get_json", return_value={"state": "APPROVED", "body": "Exploded"})
    assert trigger.is_build_finished(mock_pr, mock_trigger_config) is False

    mocker.patch("openqabot.giteatrigger.gitea.get_json", return_value={"state": "PENDING", "body": ""})
    assert trigger.is_build_finished(mock_pr, mock_trigger_config) is False


def test_comment_on_pr_exception(trigger: GiteaTrigger) -> None:
    """Tests comment_on_pr when fetching jobs fails."""
    cast("MagicMock", trigger.openqa.get_jobs).side_effect = RequestError("GET", "http://openqa", 500, "error")

    mock_pr = MagicMock(number=123)
    # Should not raise exception
    data = Data(123, "git", 0, "flavor", "arch", "distri", "version", "build", "product")
    trigger.comment_on_pr(mock_pr, [data])


def test_trigger_init_maintenance(
    mock_args: Namespace, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
    """Cover the maintenance initialization path."""
    mock_args.maintenance = True
    mocker.patch("openqabot.giteatrigger.OpenQAInterface")
    mocker.patch("openqabot.loader.gitea.make_token_header")
    mocker.patch("openqabot.giteatrigger.get_configs_from_path", return_value=[mock_trigger_config])
    trigger = GiteaTrigger(mock_args)
    assert trigger.is_maintenance is True
    assert not hasattr(trigger, "qa_labels")


def test_is_openqa_triggering_needed_with_results(trigger: GiteaTrigger, mock_trigger_config: TriggerConfig) -> None:
    """Tests is_openqa_triggering_needed when results are found."""
    cast("MagicMock", trigger.openqa.get_scheduled_product_stats).return_value = {"job": "done"}
    mock_iso = MagicMock()
    assert trigger.is_openqa_triggering_needed(mock_iso, mock_trigger_config) is False


def test_trigger_init_no_configs(mock_args: Namespace, mocker: MockerFixture) -> None:
    """Verify that ValueError is raised if no configs are found."""
    mocker.patch("openqabot.giteatrigger.get_configs_from_path", return_value=[])
    mocker.patch("openqabot.loader.gitea.make_token_header")

    with pytest.raises(ValueError, match="No configs were found"):
        GiteaTrigger(mock_args)


def test_build_openqa_settings_no_iso_name(trigger: GiteaTrigger, mock_trigger_config: TriggerConfig) -> None:
    """Test _build_openqa_settings when is_maintenance is False and iso_name is None."""
    trigger.is_maintenance = False
    mock_pr = MagicMock(
        spec=PullRequest, number=123, commit_sha="sha123", project="project", branch="main", url="http://fake-url"
    )

    matched_iso = MagicMock()
    matched_iso.product = "SLES"
    matched_iso.version = "15.5"
    matched_iso.arch = "x86_64"
    matched_iso.build = "PR-123"

    settings = trigger._build_openqa_settings(mock_pr, mock_trigger_config, matched_iso, "http://repo", None)  # noqa: SLF001
    assert "ISO_1_URL" not in settings
    assert "HDD_1_URL" not in settings


def test_is_build_finished_request_exception(
    trigger: GiteaTrigger, mocker: MockerFixture, mock_trigger_config: TriggerConfig
) -> None:
    """Test is_build_finished when get_events_by_timeline raises RequestException."""
    mocker.patch(
        "openqabot.loader.gitea.get_events_by_timeline", side_effect=requests.exceptions.RequestException("API Down")
    )
    mock_pr = MagicMock(number=123)
    assert trigger.is_build_finished(mock_pr, mock_trigger_config) is False
