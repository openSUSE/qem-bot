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
    mocker.patch("openqabot.loader.gitea.OBS_REPO_TYPE", "match")
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
    mocker.patch("openqabot.loader.gitea.OBS_REPO_TYPE", None)
    res = {"arch": "s390x"}
    assert not gitea.is_build_result_relevant(res, {"x86_64"})
    assert gitea.is_build_result_relevant(res, {"s390x"})


def test_add_build_result_published(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="SLES")
    mocker.patch("openqabot.loader.gitea.OBS_PRODUCTS", ["SLES"])
    mocker.patch("openqabot.loader.gitea.add_channel_for_build_result", return_value="chan")
    incident = {}
    res = mocker.Mock()
    res.findall.return_value = []
    res.get.side_effect = lambda k: "other" if k == "state" else "val"
    results = BuildResults()
    gitea.add_build_result(incident, res, results)
    assert "chan" in results.unpublished

    mocker.patch("openqabot.loader.gitea.OBS_PRODUCTS", ["all"])
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="Foo")
    results.unpublished.clear()
    gitea.add_build_result(incident, res, results)
    assert "chan" in results.unpublished

    mocker.patch("openqabot.loader.gitea.OBS_PRODUCTS", ["SLES"])
    results.unpublished.clear()
    gitea.add_build_result(incident, res, results)
    assert "chan" not in results.unpublished


def test_add_build_results_failed_packages(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.determine_relevant_archs_from_multibuild_info", return_value=None)
    mocker.patch("openqabot.loader.gitea.OBS_REPO_TYPE", None)
    xml_data = """
    <buildresults>
        <result project="proj" repository="repo" arch="x86_64" state="published">
            <status package="pkg1" code="failed"/>
        </result>
    </buildresults>
    """
    mocker.patch("openqabot.loader.gitea.http_GET", return_value=BytesIO(xml_data.encode()))
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="SLES")
    mocker.patch("openqabot.loader.gitea.OBS_PRODUCTS", ["SLES"])
    incident = {"number": 123}
    gitea.add_build_results(incident, ["http://obs/project/show/proj"], dry=False)
    assert "PR git:123: Some packages failed: pkg1" in caplog.text
    assert "pkg1" in cast("list", incident["failed_or_unpublished_packages"])


def test_is_build_result_relevant_repo_match(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.OBS_REPO_TYPE", "standard")
    res = {"repository": "standard", "arch": "x86_64"}
    assert gitea.is_build_result_relevant(res, {"x86_64"})


def test_add_build_results_dry_124(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.determine_relevant_archs_from_multibuild_info", return_value=None)
    mock_read_xml = mocker.patch("openqabot.loader.gitea.read_xml")
    mock_read_xml.return_value.getroot.return_value.findall.return_value = []
    incident = {"number": 124}
    gitea.add_build_results(incident, ["http://obs/project/show/proj"], dry=True)
    mock_read_xml.assert_called_once_with("build-results-124-proj")
