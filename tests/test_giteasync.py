# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# ruff: noqa: S106 "Possible hardcoded password assigned to argument"

import logging
import re
import urllib.error
from collections.abc import Generator
from pathlib import Path
from typing import Any, NamedTuple
from unittest.mock import MagicMock
from urllib.parse import urljoin

import pytest
from lxml import etree
from pytest_mock import MockerFixture

import responses
from openqabot.config import OBS_DOWNLOAD_URL, OBS_URL, QEM_DASHBOARD
from openqabot.giteasync import GiteaSync
from openqabot.loader.gitea import (
    add_build_results,
    compute_repo_url_for_job_setting,
    get_product_name,
    get_product_name_and_version_from_scmsync,
    read_json,
    read_utf8,
    read_xml,
    review_pr,
)
from openqabot.types import Repos
from responses import GET, matchers


class Namespace(NamedTuple):
    dry: bool
    fake_data: bool
    token: str
    gitea_token: str
    retry: bool
    gitea_repo: str
    allow_build_failures: bool
    consider_unrequested_prs: bool
    pr_number: int


@pytest.fixture
def fake_gitea_api() -> None:
    host = "https://src.suse.de"
    pulls_url = urljoin(host, "api/v1/repos/products/SLFO/pulls")
    issues_url = urljoin(host, "api/v1/repos/products/SLFO/issues")
    # ruff: noqa: E501 line-too-long
    patchinfo_path = "products/SLFO/raw/commit/2cf58b3a9c32d139470a5f32d5aa64efbd0fa90dda0144b09421709252fcb0ea/patchinfo.23193048203482931/_patchinfo"
    patchinfo_data = Path("responses/patch-info.xml").read_bytes()
    responses.add(GET, pulls_url + "?state=open&page=1", json=read_json("pulls"))
    responses.add(GET, re.compile(pulls_url + r"\?state=open&page=.*"), json=[])
    responses.add(GET, pulls_url + "/124/reviews", json=read_json("reviews-124"))
    responses.add(GET, pulls_url + "/124/files", json=read_json("files-124"))
    responses.add(GET, re.compile(pulls_url + r"/.*/reviews"), json=[])
    responses.add(GET, re.compile(pulls_url + r"/.*/files"), json=[])
    responses.add(GET, issues_url + "/124/comments", json=read_json("comments-124"))
    responses.add(GET, re.compile(issues_url + r"/.*/comments"), json=[])
    responses.add(GET, urljoin(host, patchinfo_path), body=patchinfo_data)


@pytest.fixture
def fake_gitea_api_post_review_comment() -> None:
    url = "https://src.suse.de/api/v1/repos/orga/repo/issues/42/comments"
    msg = "@qam-openqa-review: approved\naccepted\nTested commit: 12345"
    responses.post(url, match=[matchers.json_params_matcher({"body": msg})])


@pytest.fixture
def fake_dashboard_replyback() -> None:
    def reply_callback(request: Any) -> tuple[int, list, Any]:
        return (200, [], request.body)

    responses.add_callback(
        responses.PATCH,
        re.compile(f"{QEM_DASHBOARD}api/incidents"),
        callback=reply_callback,
        match=[matchers.query_param_matcher({"type": "git"})],
    )


@pytest.fixture
def fake_repo() -> None:
    url = f"{OBS_DOWNLOAD_URL}/SUSE:/SLFO:/1.1.99:/PullRequest:/124:/SLES/standard/repo?jsontable"
    listing = Path("responses/test-product-repo.json").read_bytes()
    responses.add(GET, url, body=listing)


@pytest.fixture
def mock_http_get_fixture(mocker: MockerFixture) -> Generator[MagicMock, Any, Any]:
    return mocker.patch("osc.core.http_GET")


def fake_osc_http_get(url: str) -> etree.ElementTree:
    if url == "https://api.suse.de/build/SUSE:SLFO:1.1.99:PullRequest:124/_result":
        return read_xml("build-results-124-SUSE:SLFO:1.1.99:PullRequest:124")
    if url == "https://api.suse.de/build/SUSE:SLFO:1.1.99:PullRequest:124:SLES/_result":
        return read_xml("build-results-124-SUSE:SLFO:1.1.99:PullRequest:124:SLES")
    raise AssertionError("Code tried to query unexpected OSC URL: " + url)  # pragma: no cover


def noop_osc_http_get(_url: str) -> etree.ElementTree:
    return read_xml("empty-build-results")


def fake_osc_xml_parse(data: Any) -> Any:
    return data  # fake_osc_http_get already returns parsed XML so just return that


def fake_urllib_http_error(data: Any) -> Any:
    with Path("responses/empty-build-results.xml").open(encoding="utf-8") as fp:
        raise urllib.error.HTTPError(data, 404, "Not found", {}, fp)


def fake_osc_get_config(override_apiurl: str) -> None:
    assert override_apiurl == OBS_URL


def fake_get_multibuild_data(obs_project: str) -> str:
    assert obs_project == "SUSE:SLFO:1.1.99:PullRequest:124:SLES"
    return read_utf8("_multibuild-124-" + obs_project + ".xml")


def run_gitea_sync(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    *,
    no_build_results: bool = False,
    allow_failures: bool = True,
    dry: bool = False,
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.giteasync")
    caplog.set_level(logging.DEBUG, logger="bot.loader.gitea")

    http_get_patch_target = "osc.core.http_GET"
    xml_parse_patch_target = "osc.util.xml.xml_parse"
    get_config_patch_target = "osc.conf.get_config"
    get_multibuild_data_patch_target = "openqabot.loader.gitea.get_multibuild_data"

    mocker.patch(http_get_patch_target, side_effect=noop_osc_http_get if no_build_results else fake_osc_http_get)
    mocker.patch(xml_parse_patch_target, side_effect=fake_osc_xml_parse)
    mocker.patch(get_config_patch_target, side_effect=fake_osc_get_config)
    mocker.patch(get_multibuild_data_patch_target, side_effect=fake_get_multibuild_data)
    args = Namespace(
        dry=dry,
        fake_data=False,
        token="123",
        gitea_token="456",
        retry=False,
        gitea_repo="products/SLFO",
        allow_build_failures=allow_failures,
        consider_unrequested_prs=False,
        pr_number=None,
    )
    assert GiteaSync(args)() == 0


@responses.activate
@pytest.mark.usefixtures("fake_gitea_api", "fake_dashboard_replyback")
def test_gitea_sync_on_dry_run_does_not_sync(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    run_gitea_sync(mocker, caplog, dry=True)
    assert "Dry run, nothing synced" in caplog.text


@responses.activate
@pytest.mark.usefixtures("fake_gitea_api", "fake_dashboard_replyback")
def test_sync_with_product_repo(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    run_gitea_sync(mocker, caplog)
    messages = [x[-1] for x in caplog.record_tuples]
    expected_repo = "SUSE:SLFO:1.1.99:PullRequest:124:SLES"
    assert "Relevant archs for " + expected_repo + ": ['aarch64', 'x86_64']" in messages
    assert "Loaded 7 active PRs/incidents from products/SLFO" in messages
    assert "Getting info about PR 131 from Gitea" in messages
    assert "Updating info about 1 incidents" in messages
    assert len(responses.calls) == 25
    assert len(responses.calls[-1].response.json()) == 1
    incident = responses.calls[-1].response.json()[0]
    assert incident["number"] == 124
    assert incident["packages"] == ["tree"]
    channels = incident["channels"]
    failed_or_unpublished = incident["failed_or_unpublished_packages"]
    for arch in ["aarch64", "x86_64"]:  # ppc64le skipped as not present in _multibuild
        channel = "#".join([f"{expected_repo}:{arch}", "15.99"])
        assert channel in channels
        assert channel in failed_or_unpublished
    assert incident["project"] == "SLFO"
    assert incident["url"] == "https://src.suse.de/products/SLFO/pulls/124"
    assert incident["inReview"]
    assert incident["inReviewQAM"]
    assert incident["isActive"]
    assert not incident["approved"]
    assert not incident["embargoed"]
    assert incident["priority"] == 0

    # expect the scminfo from the product repo of the configured product
    assert "18bfa2a23fb7985d5d0" in incident["scminfo"]
    assert "18bfa2a23fb7985d5d0" in incident["scminfo_SLES"]


@responses.activate
@pytest.mark.usefixtures("fake_gitea_api", "fake_repo", "fake_dashboard_replyback")
def test_sync_with_product_version_from_repo_listing(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mocker.patch("openqabot.loader.gitea.OBS_REPO_TYPE", "standard")  # has no scmsync so repo listing is used
    run_gitea_sync(mocker, caplog)

    expected_repo = "SUSE:SLFO:1.1.99:PullRequest:124:SLES"
    incident = responses.calls[-1].response.json()[0]
    channels = incident["channels"]
    for arch in ["aarch64", "x86_64"]:  # ppc64le skipped as not present in _multibuild
        channel = "#".join([f"{expected_repo}:{arch}", "16.0"])  # the 16.0 comes from repo listing
        assert channel in channels
    requests_to_download_repo = [r for r in responses.calls if r.request.url.startswith(OBS_DOWNLOAD_URL)]
    assert len(requests_to_download_repo) == 1


@responses.activate
@pytest.mark.usefixtures("fake_gitea_api", "fake_dashboard_replyback")
def test_sync_with_codestream_repo(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch("openqabot.loader.gitea.OBS_REPO_TYPE", "standard")
    mocker.patch("openqabot.loader.gitea.OBS_PRODUCTS", "")
    run_gitea_sync(mocker, caplog)

    # expect the codestream repo to be used
    expected_repo = "SUSE:SLFO:1.1.99:PullRequest:124"
    incident = responses.calls[-1].response.json()[0]
    channels = incident["channels"]
    failed_or_unpublished = incident["failed_or_unpublished_packages"]
    for arch in ["ppc64le", "aarch64", "x86_64"]:
        channel = f"{expected_repo}:{arch}"
        assert channel in channels
        assert channel in failed_or_unpublished

    # expect the scminfo from the codestream repo
    assert "f229fea352e8f268960" in incident["scminfo"]
    assert "18bfa2a23fb7985d5d0" in incident["scminfo_SLES"]


@responses.activate
@pytest.mark.usefixtures("fake_gitea_api", "fake_dashboard_replyback")
def test_sync_without_results(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    run_gitea_sync(mocker, caplog, no_build_results=True, allow_failures=False)
    messages = [x[-1] for x in caplog.record_tuples]
    m = "Skipping PR 124, no packages have been built/published (there are 0 failed/unpublished packages)"
    assert m in messages


def test_extracting_product_name_and_version() -> None:
    assert get_product_name("1.1.99:PullRequest:166") == ""
    assert get_product_name("1.1.99:PullRequest:166:SLES") == "SLES"

    slfo_url = "https://src.suse.de/user1/SLFO.git?onlybuild=tree#f229f"
    prod_ver = get_product_name_and_version_from_scmsync(slfo_url)
    assert prod_ver == ("", "")
    prod_url = "https://src.suse.de/products/SLES#15.99"
    prod_ver = get_product_name_and_version_from_scmsync(prod_url)
    assert prod_ver == ("SLES", "15.99")


def test_handling_unavailable_build_info(caplog: pytest.LogCaptureFixture, mock_http_get_fixture: MagicMock) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    mock_http_get_fixture.side_effect = fake_urllib_http_error
    incident = {}
    add_build_results(incident, ["https://foo/project/show/bar"], dry=False)
    assert incident["successful_packages"] == []
    assert incident["failed_or_unpublished_packages"] == ["bar"]
    assert "Unable to read build results of project" in caplog.text
    assert "Traceback" not in caplog.text


@responses.activate
@pytest.mark.usefixtures("fake_gitea_api_post_review_comment")
def test_reviewing_pr() -> None:
    review_pr({"token": "foo"}, "orga/repo", 42, "accepted", "12345", approve=True)


def test_computing_repo_url() -> None:
    repos = Repos("product", "1.2", "x86_64")

    url = compute_repo_url_for_job_setting("base", repos, "Foo", "16.0")
    expected_url = "base/product:/1.2/product/repo/Foo-16.0-x86_64/"
    assert url == expected_url

    url = compute_repo_url_for_job_setting("base", repos, ["Foo", "Foo-Bar"], "16.0")
    expected_url += ",base/product:/1.2/product/repo/Foo-Bar-16.0-x86_64/"
    assert url == expected_url
