# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test OBS build results."""

import json
import logging
import urllib.error
from http import HTTPStatus
from io import BytesIO
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
import requests
from lxml import etree  # ty: ignore[unresolved-import]
from pytest_mock import MockerFixture

from openqabot.loader import obs
from openqabot.loader.obs import BuildResults


def test_add_build_result_inconsistent_scminfo(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="bot.loader.obs")
    incident = {"scminfo": "old", "number": 1, "project": "owner/repo"}
    res = mocker.Mock()
    res.get.return_value = "project"
    res.findall.return_value = [mocker.Mock(text="new")]
    mocker.patch("openqabot.loader.obs.add_channel_for_build_result")
    obs.add_build_result(incident, res, BuildResults())
    assert "PR git:owner/repo:1: Inconsistent SCM info for project project: found 'new' vs 'old'" in caplog.text


def test_is_build_result_relevant_repo_mismatch(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.config.settings.obs_repo_type", "match")
    res = {"repository": "mismatch", "arch": "x86_64"}
    assert not obs.is_build_result_relevant(res, {"x86_64"})


def test_add_build_results_url_mismatch_just_passes() -> None:
    obs.add_build_results({}, ["http://nomatch.com"], fake_data=True)


def test_add_build_results_http_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.obs")
    mocker.patch("openqabot.loader.obs.determine_relevant_archs", return_value=None)
    err = urllib.error.HTTPError("url", 404, "msg", cast("Any", {}), None)
    mocker.patch("openqabot.loader.obs.http_GET", side_effect=err)
    incident = {"number": 123, "packages": []}
    obs.add_build_results(incident, ["http://obs/project/show/proj"], fake_data=False)
    assert "Build results for project proj unreadable, skipping" in caplog.text
    assert "proj" in cast("list", incident["failed_or_unpublished_packages"])


def test_is_build_result_relevant_arch_filter(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.config.settings.obs_repo_type", None)
    res = {"arch": "s390x"}
    assert not obs.is_build_result_relevant(res, {"x86_64"})
    assert obs.is_build_result_relevant(res, {"s390x"})


def test_add_build_result_published(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.obs.get_product_name", return_value="SLES")
    mocker.patch("openqabot.config.settings.obs_products", "SLES")
    mocker.patch("openqabot.loader.obs.add_channel_for_build_result", return_value="chan")
    incident = {}
    res = mocker.Mock()
    res.findall.return_value = []
    res.get.side_effect = lambda k: "other" if k == "state" else "val"
    results = BuildResults()
    obs.add_build_result(incident, res, results)
    assert "chan" in results.unpublished

    mocker.patch("openqabot.config.settings.obs_products", "all")
    mocker.patch("openqabot.loader.obs.get_product_name", return_value="Foo")
    results.unpublished.clear()
    obs.add_build_result(incident, res, results)
    assert "chan" in results.unpublished

    mocker.patch("openqabot.config.settings.obs_products", "SLES")
    results.unpublished.clear()
    obs.add_build_result(incident, res, results)
    assert "chan" not in results.unpublished


def test_add_build_results_failed_packages(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.obs")
    mocker.patch("openqabot.loader.obs.determine_relevant_archs", return_value=None)
    mocker.patch("openqabot.config.settings.obs_repo_type", None)
    mocker.patch("openqabot.loader.obs.get_product_version_from_repo_listing", return_value="15.4")
    xml_data = """
    <buildresults>
        <result project="proj" repository="repo" arch="x86_64" state="published">
            <status package="pkg1" code="failed"/>
        </result>
    </buildresults>
    """
    mocker.patch("openqabot.loader.obs.http_GET", return_value=BytesIO(xml_data.encode()))
    mocker.patch("openqabot.loader.obs.get_product_name", return_value="SLES")
    mocker.patch("openqabot.config.settings.obs_products", "SLES")
    incident = {"number": 123, "project": "owner/repo", "packages": []}
    obs.add_build_results(incident, ["http://obs/project/show/proj"], fake_data=False)
    assert "PR git:owner/repo:123: Some packages failed: pkg1" in caplog.text
    assert "pkg1" in cast("list", incident["failed_or_unpublished_packages"])


def test_is_build_result_relevant_repo_match(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.config.settings.obs_repo_type", "standard")
    res = {"repository": "standard", "arch": "x86_64"}
    assert obs.is_build_result_relevant(res, {"x86_64"})


def test_add_build_results_dry_124(mocker: MockerFixture) -> None:
    mock_archs = mocker.patch("openqabot.loader.obs.determine_relevant_archs", return_value=None)
    mock_read_xml = mocker.patch("openqabot.loader.obs.read_xml")
    mock_read_xml.return_value.getroot.return_value.findall.return_value = []
    incident = {"number": 124, "packages": ["tree"]}
    obs.add_build_results(incident, ["http://obs/project/show/proj"], fake_data=True)
    mock_read_xml.assert_called_once_with("build-results-124-proj")
    mock_archs.assert_called_once_with("proj", packages=["tree"], fake_data=True)


def test_add_build_results_scminfo(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.obs.determine_relevant_archs", return_value=None)
    mocker.patch("openqabot.config.settings.obs_products", "SLES")
    mock_read_xml = mocker.patch("openqabot.loader.obs.read_xml")
    mock_read_xml.return_value.getroot.return_value.findall.return_value = []
    incident = {"number": 124, "scminfo_SLES": "123", "packages": []}
    obs.add_build_results(incident, ["http://obs/project/show/proj"], fake_data=True)
    assert incident["scminfo"] == "123"


def test_add_build_results_duplicate_channels(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.obs.determine_relevant_archs", return_value=None)
    mocker.patch("openqabot.loader.obs.get_product_name", return_value="SLES")

    def mock_add_channel(_project: str, _arch: str, _product: str, _res: Any, projects: set[str]) -> str:
        projects.add("chan")
        return "chan"

    mocker.patch("openqabot.loader.obs.add_channel_for_build_result", side_effect=mock_add_channel)
    mocker.patch("openqabot.config.settings.obs_products", "SLES")

    xml_data = """
    <buildresults>
        <result project="proj" repository="product" arch="x86_64" state="published">
            <status package="pkg1" code="succeeded"/>
        </result>
    </buildresults>
    """
    mocker.patch("openqabot.loader.obs.http_GET", return_value=BytesIO(xml_data.encode()))

    submission = {"channels": ["chan"], "number": 123, "packages": []}
    obs.add_build_results(submission, ["http://obs/project/show/proj"], fake_data=False)
    assert submission["channels"] == ["chan"]


def test_obs_project_regex_robust() -> None:
    """Verify that OBS_PROJECT_SHOW_REGEX handles robust URLs."""
    url = "https://build.suse.de/project/show/PROJ1"
    match = obs.OBS_PROJECT_SHOW_REGEX.search(url)
    assert match is not None
    assert match.group(1) == "PROJ1"


def test_get_product_version_from_repo_listing_json_error(mocker: MockerFixture) -> None:
    mock_log = mocker.patch("openqabot.loader.obs.log")
    mock_response = MagicMock()
    mock_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
    mocker.patch.object(obs.retried_requests, "get", return_value=mock_response)
    res = obs.get_product_version_from_repo_listing("project", "product", "repo")
    assert not res
    assert mock_log.info.called


@pytest.mark.parametrize(
    ("response", "expected_log_level"),
    [
        (None, "warning"),
        (MagicMock(status_code=HTTPStatus.NOT_FOUND), "info"),
        (MagicMock(status_code=HTTPStatus.INTERNAL_SERVER_ERROR), "warning"),
    ],
)
def test_get_product_version_from_repo_listing_http_error(
    mocker: MockerFixture, response: MagicMock | None, expected_log_level: str
) -> None:
    obs.repo_listing.cache_clear()
    mock_log = mocker.patch("openqabot.loader.obs.log")
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("error", response=response)
    mocker.patch.object(obs.retried_requests, "get", return_value=mock_response)
    res = obs.get_product_version_from_repo_listing("project", "product", "repo")
    assert not res
    if expected_log_level == "info":
        assert mock_log.info.called
        assert not mock_log.warning.called
    else:
        assert mock_log.warning.called
        assert not mock_log.info.called


def test_get_product_version_from_repo_listing_request_exception(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    obs.repo_listing.cache_clear()
    caplog.set_level(logging.WARNING, logger="bot.loader.obs")
    mocker.patch("openqabot.loader.obs.retried_requests.get", side_effect=requests.RequestException("error"))
    res = obs.get_product_version_from_repo_listing("project", "product", "repo")
    assert not res
    assert "Product version unresolved" in caplog.text


def test_get_product_version_from_repo_listing_success(mocker: MockerFixture) -> None:
    obs.repo_listing.cache_clear()
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"name": "SLES-15-SP4-x86_64"},
            {"name": "other-pkg"},
        ]
    }
    mocker.patch("openqabot.loader.obs.retried_requests.get", return_value=mock_response)
    # product name 'SLES', prefix 'SLES-'
    # _extract_version will be called with name 'SLES-15-SP4-x86_64' and prefix 'SLES-'
    # remainder '15-SP4-x86_64', next(...) returns '15'
    res = obs.get_product_version_from_repo_listing("project", "SLES", "repo")
    assert res == "15"


def test_get_product_version_from_repo_listing_requests_json_error(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    obs.repo_listing.cache_clear()
    caplog.set_level(logging.INFO, logger="bot.loader.obs")
    mock_response = MagicMock()
    # Use a dummy exception that mimics requests.exceptions.JSONDecodeError if needed,
    # but requests.exceptions.JSONDecodeError should work.
    mock_response.json.side_effect = requests.exceptions.JSONDecodeError("msg", "doc", 0)
    mocker.patch("openqabot.loader.obs.retried_requests.get", return_value=mock_response)
    res = obs.get_product_version_from_repo_listing("project_json", "product_json", "repo_json")
    assert not res
    assert "Invalid JSON document" in caplog.text


def test_get_product_version_from_repo_listing_without_a_data_field(mocker: MockerFixture) -> None:
    obs.repo_listing.cache_clear()
    mocked_response = MagicMock()
    mocked_response.json.return_value = {"rows": []}
    mocker.patch("openqabot.loader.obs.retried_requests.get", return_value=mocked_response)

    assert not obs.get_product_version_from_repo_listing("project", "product", "repo")


def test_add_channel_for_build_result_local() -> None:
    projects: set[str] = set()
    res = obs.add_channel_for_build_result("myproj", "local", "myprod", None, projects)
    assert res == "myproj:local"
    assert len(projects) == 0


def test_update_scminfo_coverage(caplog: pytest.LogCaptureFixture) -> None:
    submission = {"number": 123, "project": "owner/repo"}
    res = etree.fromstring("<root><scminfo></scminfo><scminfo>new</scminfo><scminfo>other</scminfo></root>")
    obs._update_scminfo(submission, res, "project", "")  # ruff: ignore[private-member-access]
    assert submission["scminfo"] == "new"
    assert "Inconsistent SCM info" in caplog.text

    caplog.clear()
    submission = {"number": 123, "project": "owner/repo", "scminfo_prod": "old"}
    res = etree.fromstring("<root><scminfo>new</scminfo></root>")
    obs._update_scminfo(submission, res, "project", "prod")  # ruff: ignore[private-member-access]
    assert submission["scminfo_prod"] == "old"
    assert "Inconsistent SCM info" in caplog.text
