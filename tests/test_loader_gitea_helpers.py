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
from openqabot.types.gitea import BuildTarget, RepoConfig


def test_post_json_on_not_ok_logs_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger="bot.loader.gitea")
    mocked_post = mocker.Mock()
    mocked_post.ok = False
    mocker.patch("openqabot.loader.gitea.retried_requests.post", return_value=mocked_post)
    gitea.post_json("foo", {}, {}, host="my.host")
    assert "Gitea API error: POST to my.host/api/v1/foo" in caplog.text


def test_get_product_version_from_repo_listing_json_error(mocker: MockerFixture) -> None:
    mock_log = mocker.patch("openqabot.loader.gitea.log")
    mock_response = MagicMock()
    mock_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
    mocker.patch.object(gitea.retried_requests, "get", return_value=mock_response)
    res = gitea.get_product_version_from_repo_listing("project", "product", "repo", "http://obs.url")
    assert not res
    assert mock_log.info.called


def test_get_product_version_from_repo_listing_http_error(mocker: MockerFixture) -> None:
    gitea.get_product_version_from_repo_listing.cache_clear()
    mock_log = mocker.patch("openqabot.loader.gitea.log")
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("error")
    mocker.patch.object(gitea.retried_requests, "get", return_value=mock_response)
    res = gitea.get_product_version_from_repo_listing("project", "product", "repo", "http://obs.url")
    assert not res
    assert mock_log.warning.called


def test_get_product_version_from_repo_listing_request_exception(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    gitea.get_product_version_from_repo_listing.cache_clear()
    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.retried_requests.get", side_effect=requests.RequestException("error"))
    res = gitea.get_product_version_from_repo_listing("project", "product", "repo", "http://obs.url")
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
    res = gitea.get_product_version_from_repo_listing("project", "SLES", "repo", "http://obs.url")
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
    res = gitea.get_product_version_from_repo_listing("project_json", "product_json", "repo_json", "http://obs.url")
    assert not res
    assert "Invalid JSON document" in caplog.text


def test_add_channel_for_build_result_local() -> None:
    projects: set[str] = set()
    res = gitea.add_channel_for_build_result(
        BuildTarget("myproj", "local", "myprod"),
        None,
        projects,
        config=RepoConfig(
            repo_type="product",
            download_base_url="http://base.url",
            obs_download_url="http://obs.url",
            obs_products={"all"},
        ),
    )
    assert res == "myproj:local"
    assert len(projects) == 0


def test_is_build_acceptable_fail(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    incident = {"failed_or_unpublished_packages": ["pkg1"], "successful_packages": ["pkg2"]}
    assert not gitea.is_build_acceptable_and_log_if_not(incident, 123)
    assert "Skipping PR git:123: Not all packages succeeded or published" in caplog.text


def test_is_build_acceptable_success() -> None:
    incident = {"failed_or_unpublished_packages": [], "successful_packages": ["pkg1"]}
    assert gitea.is_build_acceptable_and_log_if_not(incident, 123)


def test_generate_repo_url_success(mocker: MockerFixture) -> None:
    """Covert the actual logic of generate_repo_url."""
    mock_pr = mocker.Mock()
    mock_pr.repo_name = "products/sle"
    mock_pr.branch = "main"
    mock_pr.number = 555
    mock_pr.product = "SLES"

    mocker.patch("openqabot.config.settings.gitea_url", "https://gitea.com")
    mocker.patch("openqabot.config.settings.obs_download_url", "https://download.obs.com")

    mock_response = mocker.Mock()
    mock_response.json.return_value = {"StagingProject": "openQA:Staging:A"}
    mock_get = mocker.patch("openqabot.loader.gitea.retried_requests.get", return_value=mock_response)

    url = gitea.generate_repo_url(mock_pr, {"Authorization": "token test"})

    assert url == "https://download.obs.com/openQA:/Staging:/A:/555:/SLES/product/iso"

    expected_gitea_url = "https://gitea.com/products/products/sle/raw/branch/main/staging.config"
    mock_get.assert_called_once()
    assert mock_get.call_args[0][0] == expected_gitea_url
