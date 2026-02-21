# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test Gitea sync."""

from __future__ import annotations

import logging
import re
from argparse import Namespace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.error import HTTPError
from urllib.parse import urljoin, urlparse

import pytest
from lxml import etree  # noqa: TC002  # type: ignore[unresolved-import]

import responses
from openqabot.config import settings
from openqabot.giteasync import GiteaSync
from openqabot.loader.gitea import (
    add_build_results,
    add_packages_from_files,
    compute_repo_url_for_job_setting,
    get_product_name,
    get_product_name_and_version_from_scmsync,
    read_json,
    read_utf8,
    read_xml,
    review_pr,
)
from openqabot.types.types import ProdVer, Repos
from responses import GET, matchers

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


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
    def reply_callback(request: Any) -> tuple[int, dict[str, str], Any]:
        return (200, {}, request.body)

    responses.add_callback(
        responses.PATCH,
        re.compile(f"{settings.qem_dashboard_url}api/incidents"),
        callback=reply_callback,
        match=[matchers.query_param_matcher({"type": "git"})],
    )


@pytest.fixture
def fake_repo() -> None:
    url = f"{settings.obs_download_url}/SUSE:/SLFO:/1.1.99:/PullRequest:/124:/SLES/standard/repo?jsontable"
    listing = Path("responses/test-product-repo.json").read_bytes()
    responses.add(GET, url, body=listing)


def fake_osc_http_get(url: str) -> etree.ElementTree:
    if url == f"{settings.obs_url}/build/SUSE:SLFO:1.1.99:PullRequest:124/_result":
        return read_xml("build-results-124-SUSE:SLFO:1.1.99:PullRequest:124")
    if url == f"{settings.obs_url}/build/SUSE:SLFO:1.1.99:PullRequest:124:SLES/_result":
        return read_xml("build-results-124-SUSE:SLFO:1.1.99:PullRequest:124:SLES")
    raise AssertionError("Code tried to query unexpected OSC URL: " + url)  # pragma: no cover


def noop_osc_http_get(_url: str) -> etree.ElementTree:
    return read_xml("empty-build-results")


def fake_osc_xml_parse(data: Any) -> Any:
    return data  # fake_osc_http_get already returns parsed XML so just return that


def fake_urllib_http_error(data: Any) -> Any:
    with Path("responses/empty-build-results.xml").open("rb") as fp:
        raise HTTPError(data, 404, "Not found", cast("Any", {}), fp)


def fake_osc_get_config(override_apiurl: str) -> None:
    assert override_apiurl == settings.obs_url


def fake_get_multibuild_data(obs_project: str) -> str:
    assert obs_project == "SUSE:SLFO:1.1.99:PullRequest:124:SLES"
    return read_utf8("_multibuild-124-" + obs_project + ".xml")


@pytest.fixture
def args() -> Namespace:
    return Namespace(
        dry=False,
        fake_data=False,
        token="123",
        gitea_token="456",
        retry=False,
        gitea_repo="products/SLFO",
        allow_build_failures=True,
        consider_unrequested_prs=False,
        pr_number=None,
        openqa_instance=urlparse("https://openqa.suse.de"),
    )


@pytest.fixture
def gitea_sync_mocks(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.http_GET", side_effect=fake_osc_http_get)
    mocker.patch("osc.util.xml.xml_parse", side_effect=fake_osc_xml_parse)
    mocker.patch("osc.conf.get_config", side_effect=fake_osc_get_config)
    mocker.patch("openqabot.loader.gitea.get_multibuild_data", side_effect=fake_get_multibuild_data)


def run_gitea_sync(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    args: Namespace,
    *,
    no_build_results: bool = False,
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.giteasync")
    caplog.set_level(logging.DEBUG, logger="bot.loader.gitea")

    if no_build_results:
        mocker.patch("openqabot.loader.gitea.http_GET", side_effect=noop_osc_http_get)

    assert GiteaSync(args)() == 0


@responses.activate
@pytest.mark.usefixtures("fake_gitea_api", "fake_dashboard_replyback", "gitea_sync_mocks")
def test_gitea_sync_on_dry_run_does_not_sync(args: Namespace, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.giteasync")
    args.dry = True
    assert GiteaSync(args)() == 0
    assert "Dry run: Would update QEM Dashboard data for 1 submissions" in caplog.text


@responses.activate
@pytest.mark.usefixtures("fake_gitea_api", "fake_dashboard_replyback", "gitea_sync_mocks")
def test_sync_with_product_repo(mocker: MockerFixture, caplog: pytest.LogCaptureFixture, args: Namespace) -> None:
    mocker.patch("openqabot.config.settings.obs_products", "SLES")
    run_gitea_sync(mocker, caplog, args)
    expected_repo = "SUSE:SLFO:1.1.99:PullRequest:124:SLES"
    assert "Relevant archs for " + expected_repo + ": ['aarch64', 'x86_64']" in caplog.messages
    assert "Loaded 7 active PRs from products/SLFO" in caplog.messages
    assert "Fetching info for PR git:131 from Gitea" in caplog.messages
    assert "Syncing Gitea PRs to QEM Dashboard: Considering 1 submissions" in caplog.messages
    assert len(responses.calls) == 25
    assert len(cast("Any", responses.calls[-1].response).json()) == 1
    submission = cast("Any", responses.calls[-1].response).json()[0]
    assert submission["number"] == 124
    assert submission["packages"] == ["tree"]
    channels = submission["channels"]
    failed_or_unpublished = submission["failed_or_unpublished_packages"]
    for arch in ["aarch64", "x86_64"]:  # ppc64le skipped as not present in _multibuild
        channel = "#".join([f"{expected_repo}:{arch}", "15.99"])
        assert channel in channels
        assert channel in failed_or_unpublished
    assert submission["project"] == "SLFO"
    assert submission["url"] == "https://src.suse.de/products/SLFO/pulls/124"
    assert submission["inReview"]
    assert submission["inReviewQAM"]
    assert submission["isActive"]
    assert not submission["approved"]
    assert not submission["embargoed"]
    assert submission["priority"] == 0

    # expect the scminfo from the product repo of the configured product
    assert "18bfa2a23fb7985d5d0" in submission["scminfo"]
    assert "18bfa2a23fb7985d5d0" in submission["scminfo_SLES"]


@responses.activate
@pytest.mark.usefixtures("fake_gitea_api", "fake_repo", "fake_dashboard_replyback", "gitea_sync_mocks")
def test_sync_with_product_version_from_repo_listing(
    mocker: MockerFixture,
    args: Namespace,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mocker.patch("openqabot.config.settings.obs_repo_type", "standard")  # has no scmsync so repo listing is used
    run_gitea_sync(mocker, caplog, args)

    expected_repo = "SUSE:SLFO:1.1.99:PullRequest:124:SLES"
    submission = cast("Any", responses.calls[-1].response).json()[0]
    channels = submission["channels"]
    for arch in ["aarch64", "x86_64"]:  # ppc64le skipped as not present in _multibuild
        channel = "#".join([f"{expected_repo}:{arch}", "16.0"])  # the 16.0 comes from repo listing
        assert channel in channels
    requests_to_download_repo = [
        r for r in responses.calls if cast("Any", r.request).url.startswith(settings.obs_download_url)
    ]
    assert len(requests_to_download_repo) == 1


@responses.activate
@pytest.mark.usefixtures("fake_gitea_api", "fake_dashboard_replyback", "gitea_sync_mocks")
def test_sync_with_codestream_repo(mocker: MockerFixture, args: Namespace, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.giteasync")
    mocker.patch("openqabot.config.settings.obs_repo_type", "standard")
    mocker.patch("openqabot.config.settings.obs_products", "")
    run_gitea_sync(mocker, caplog, args)

    # expect the codestream repo to be used


@responses.activate
@pytest.mark.usefixtures("fake_gitea_api", "fake_dashboard_replyback", "gitea_sync_mocks")
def test_sync_without_results(mocker: MockerFixture, caplog: pytest.LogCaptureFixture, args: Namespace) -> None:
    args.allow_build_failures = False
    run_gitea_sync(mocker, caplog, args, no_build_results=True)
    m = "Skipping PR git:124: No packages have been built/published (there are 0 failed/unpublished packages)"
    assert m in caplog.messages


def test_extracting_product_name_and_version() -> None:
    assert not get_product_name("1.1.99:PullRequest:166")
    assert get_product_name("1.1.99:PullRequest:166:SLES") == "SLES"

    slfo_url = "https://src.suse.de/user1/SLFO.git?onlybuild=tree#f229f"
    prod_ver = get_product_name_and_version_from_scmsync(slfo_url)
    assert prod_ver == ("", "")
    prod_url = "https://src.suse.de/products/SLES#15.99"
    prod_ver = get_product_name_and_version_from_scmsync(prod_url)
    assert prod_ver == ("SLES", "15.99")


def test_handling_unavailable_build_info(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.http_GET", side_effect=fake_urllib_http_error)
    submission = {}
    add_build_results(submission, ["https://foo/project/show/bar"], dry=False)
    assert submission["successful_packages"] == []
    assert submission["failed_or_unpublished_packages"] == ["bar"]
    assert "Build results for project bar unreadable, skipping:" in caplog.text
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

    # Test with empty product_version should now raise ValueError
    repos_no_ver = Repos("product", "1.2", "x86_64", "")
    with pytest.raises(ValueError, match="Product version must be provided for Foo"):
        compute_repo_url_for_job_setting("base", repos_no_ver, "Foo", None)


def test_computing_repo_url_empty_product() -> None:
    repo = ProdVer("product", "1.2")
    url = repo.compute_url("base", "", "x86_64")
    assert url == "base/product:/1.2/product/repodata/repomd.xml"


def test_adding_packages_from_files() -> None:
    submission = {"packages": []}
    files = [
        {"filename": "foo/_patchinfo", "raw_url": "foo"},
        {"filename": "bar/_patchinfo", "raw_url": "bar"},
        {"filename": "baz/_patchinfo", "raw_url": None},
    ]
    add_packages_from_files(submission, {}, files, dry=True)
    assert submission["packages"] == ["tree", "tree"], "package added twice (once for each patchinfo with raw_url)"
