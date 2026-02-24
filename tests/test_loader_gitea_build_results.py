# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader Gitea build results."""

import logging
import urllib.error
from io import BytesIO
from typing import Any, cast

import pytest
from pytest_mock import MockerFixture

from openqabot.loader import gitea
from openqabot.loader.gitea import BuildResults


def test_add_build_result_inconsistent_scminfo(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    incident = {"scminfo": "old", "number": 1}
    res = mocker.Mock()
    res.get.return_value = "project"
    res.findall.return_value = [mocker.Mock(text="new")]
    mocker.patch("openqabot.loader.gitea.add_channel_for_build_result")
    gitea.add_build_result(incident, res, BuildResults())
    assert "PR git:1: Inconsistent SCM info for project project: found 'new' vs 'old'" in caplog.text


def test_is_build_result_relevant_repo_mismatch(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.config.settings.obs_repo_type", "match")
    res = {"repository": "mismatch", "arch": "x86_64"}
    assert not gitea.is_build_result_relevant(res, {"x86_64"})


def test_add_build_results_url_mismatch_just_passes() -> None:
    gitea.add_build_results({}, ["http://nomatch.com"], dry=True)


def test_add_build_results_http_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.determine_relevant_archs_from_multibuild_info", return_value=None)
    err = urllib.error.HTTPError("url", 404, "msg", cast("Any", {}), None)
    mocker.patch("openqabot.loader.gitea.http_GET", side_effect=err)
    incident = {"number": 123}
    gitea.add_build_results(incident, ["http://obs/project/show/proj"], dry=False)
    assert "Build results for project proj unreadable, skipping" in caplog.text
    assert "proj" in cast("list", incident["failed_or_unpublished_packages"])


def test_is_build_result_relevant_arch_filter(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.config.settings.obs_repo_type", None)
    res = {"arch": "s390x"}
    assert not gitea.is_build_result_relevant(res, {"x86_64"})
    assert gitea.is_build_result_relevant(res, {"s390x"})


def test_add_build_result_published(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="SLES")
    mocker.patch("openqabot.config.settings.obs_products", "SLES")
    mocker.patch("openqabot.loader.gitea.add_channel_for_build_result", return_value="chan")
    incident = {}
    res = mocker.Mock()
    res.findall.return_value = []
    res.get.side_effect = lambda k: "other" if k == "state" else "val"
    results = BuildResults()
    gitea.add_build_result(incident, res, results)
    assert "chan" in results.unpublished

    mocker.patch("openqabot.config.settings.obs_products", "all")
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="Foo")
    results.unpublished.clear()
    gitea.add_build_result(incident, res, results)
    assert "chan" in results.unpublished

    mocker.patch("openqabot.config.settings.obs_products", "SLES")
    results.unpublished.clear()
    gitea.add_build_result(incident, res, results)
    assert "chan" not in results.unpublished


def test_add_build_results_failed_packages(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.determine_relevant_archs_from_multibuild_info", return_value=None)
    mocker.patch("openqabot.config.settings.obs_repo_type", None)
    xml_data = """
    <buildresults>
        <result project="proj" repository="repo" arch="x86_64" state="published">
            <status package="pkg1" code="failed"/>
        </result>
    </buildresults>
    """
    mocker.patch("openqabot.loader.gitea.http_GET", return_value=BytesIO(xml_data.encode()))
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="SLES")
    mocker.patch("openqabot.config.settings.obs_products", "SLES")
    incident = {"number": 123}
    gitea.add_build_results(incident, ["http://obs/project/show/proj"], dry=False)
    assert "PR git:123: Some packages failed: pkg1" in caplog.text
    assert "pkg1" in cast("list", incident["failed_or_unpublished_packages"])


def test_is_build_result_relevant_repo_match(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.config.settings.obs_repo_type", "standard")
    res = {"repository": "standard", "arch": "x86_64"}
    assert gitea.is_build_result_relevant(res, {"x86_64"})


def test_add_build_results_dry_124(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.determine_relevant_archs_from_multibuild_info", return_value=None)
    mock_read_xml = mocker.patch("openqabot.loader.gitea.read_xml")
    mock_read_xml.return_value.getroot.return_value.findall.return_value = []
    incident = {"number": 124}
    gitea.add_build_results(incident, ["http://obs/project/show/proj"], dry=True)
    mock_read_xml.assert_called_once_with("build-results-124-proj")


def test_add_build_results_scminfo(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.determine_relevant_archs_from_multibuild_info", return_value=None)
    mocker.patch("openqabot.config.settings.obs_products", "SLES")
    mock_read_xml = mocker.patch("openqabot.loader.gitea.read_xml")
    mock_read_xml.return_value.getroot.return_value.findall.return_value = []
    incident = {"number": 124, "scminfo_SLES": "123"}
    gitea.add_build_results(incident, ["http://obs/project/show/proj"], dry=True)
    assert incident["scminfo"] == "123"


def test_add_build_results_duplicate_channels(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.determine_relevant_archs_from_multibuild_info", return_value=None)
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="SLES")

    def mock_add_channel(_project: str, _arch: str, _product: str, _res: Any, projects: set[str]) -> str:
        projects.add("chan")
        return "chan"

    mocker.patch("openqabot.loader.gitea.add_channel_for_build_result", side_effect=mock_add_channel)
    mocker.patch("openqabot.config.settings.obs_products", "SLES")

    xml_data = """
    <buildresults>
        <result project="proj" repository="product" arch="x86_64" state="published">
            <status package="pkg1" code="succeeded"/>
        </result>
    </buildresults>
    """
    mocker.patch("openqabot.loader.gitea.http_GET", return_value=BytesIO(xml_data.encode()))

    submission = {"channels": ["chan"], "number": 123}
    gitea.add_build_results(submission, ["http://obs/project/show/proj"], dry=False)
    assert submission["channels"] == ["chan"]


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

    gitea.add_comments_and_referenced_build_results(submission, comments, dry=True)

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


def test_obs_project_regex_robust() -> None:
    """Verify that OBS_PROJECT_SHOW_REGEX handles robust URLs."""
    url = "https://build.suse.de/project/show/PROJ1"
    match = gitea.OBS_PROJECT_SHOW_REGEX.search(url)
    assert match is not None
    assert match.group(1) == "PROJ1"


def test_add_comments_no_bot_comments(mocker: MockerFixture) -> None:
    """Verify that nothing happens if no bot comments are found."""
    submission = {"number": 123, "channels": [], "packages": []}
    comments = [{"user": {"username": "someone_else"}, "body": "hello"}]
    mock_add_build_results = mocker.patch("openqabot.loader.gitea.add_build_results")
    gitea.add_comments_and_referenced_build_results(submission, comments, dry=True)
    mock_add_build_results.assert_not_called()


def test_add_comments_bot_comments_no_urls(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    """Verify that a warning is logged if bot comments exist but contain no URLs."""
    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    submission = {"number": 123, "channels": [], "packages": []}
    comments = [{"user": {"username": "autogits_obs_staging_bot"}, "body": "No URLs here"}]
    mock_add_build_results = mocker.patch("openqabot.loader.gitea.add_build_results")
    gitea.add_comments_and_referenced_build_results(submission, comments, dry=True)
    mock_add_build_results.assert_not_called()
    assert "PR git:123: No OBS URLs found in comments from autogits_obs_staging_bot" in caplog.text
