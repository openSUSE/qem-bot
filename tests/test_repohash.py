# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test RepoHash."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import ANY

import pytest
import requests
from requests import ConnectionError as RequestsConnectionError
from requests import HTTPError as RequestsHTTPError

import openqabot.loader.repohash as rp
import responses
from openqabot.config import OBS_REPO_TYPE
from openqabot.errors import NoRepoFoundError
from openqabot.loader.repohash import RepoOptions
from openqabot.types.types import Repos

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

BASE_XML = '<repomd xmlns="http://linux.duke.edu/metadata/repo" xmlns:rpm="http://linux.duke.edu/metadata/rpm"><revision>%s</revision></repomd>'
SLES = BASE_XML % "256"
PROJECT = "SUSE:Maintenance:12345"
SLES_URL = "http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLES_15SP3_x86_64/repodata/repomd.xml"


@responses.activate
def test_get_max_revision_manager_aarch64() -> None:
    arch = "aarch64"
    repos = [Repos("SLE-Module-SUSE-Manager-Server", "4.1", arch)]

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, PROJECT)


@responses.activate
def test_get_max_revision_opensuse() -> None:
    arch = "aarch64"
    repos = [Repos("openSUSE-SLE", "4.1", arch)]
    opensuse = BASE_XML % "256"
    url = "http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_openSUSE-SLE_4.1/repodata/repomd.xml"
    responses.add(responses.GET, url=url, body=opensuse)
    ret = rp.get_max_revision(repos, arch, PROJECT)
    assert ret == 256


@responses.activate
def test_get_max_revision_opensuse_colon() -> None:
    arch = "x86_64"
    repos = [Repos("openSUSE:Backports", "SLE-16.0:PullRequest:397", arch)]
    xml = BASE_XML % "512"
    url = f"http://download.opensuse.org/repositories/openSUSE:/Backports:/SLE-16.0:/PullRequest:/397/{OBS_REPO_TYPE}/repodata/repomd.xml"
    responses.add(responses.GET, url=url, body=xml)
    opts = RepoOptions(download_repo_url="http://download.opensuse.org/repositories")
    ret = rp.get_max_revision(repos, arch, "openSUSE:Backports", opts)
    assert ret == 512


arch = "x86_64"
repos = [Repos("SLES", "15SP3", arch), Repos("SLED", "15SP3", arch)]


def add_sles_sled_response(
    sled_body: str | RequestsConnectionError | RequestsHTTPError | BufferError,
) -> None:
    responses.add(responses.GET, url=SLES_URL, body=SLES)
    responses.add(responses.GET, url=SLES_URL.replace("SLES", "SLED"), body=sled_body)


@responses.activate
def test_get_max_revision_3() -> None:
    add_sles_sled_response(BASE_XML % "257")
    ret = rp.get_max_revision(repos, arch, PROJECT)
    assert ret == 257


@responses.activate
def test_get_max_revision_connectionerror(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.repohash")
    add_sles_sled_response(requests.ConnectionError("Failed"))

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, PROJECT)

    assert "%s: RepoHash metadata not found at %s" in caplog.records[0].msg
    assert "SUSE:Maintenance:12345" in cast("str", cast("Any", caplog.records[0].args)[0])


@responses.activate
def test_get_max_revision_httperror(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.repohash")
    add_sles_sled_response(requests.HTTPError("Failed"))

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, PROJECT)

    assert "%s: RepoHash metadata not found at %s" in caplog.records[0].msg


@responses.activate
def test_get_max_revision_xmlerror(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.repohash")
    add_sles_sled_response("<invalid>")

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, PROJECT)

    assert "%s: RepoHash metadata not found at %s" in caplog.records[0].msg


@responses.activate
def test_get_max_revision_empty_xml(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.repohash")
    add_sles_sled_response("<invalid></invalid>")

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, PROJECT)

    assert "%s: RepoHash calculation failed, no revision tag found in %s" in caplog.records[0].msg


@responses.activate
def test_get_max_revision_exception(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")
    add_sles_sled_response(BufferError("other error"))
    with pytest.raises(BufferError):
        rp.get_max_revision(repos, arch, PROJECT)


@responses.activate
def test_get_max_revision_retry_error(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")
    repos = [Repos("SLES", "15SP3", arch)]
    project = "SUSE:Maintenance:12345"
    responses.add(responses.GET, url=SLES_URL, body=requests.exceptions.RetryError("Max retries exceeded"))

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, project)


@responses.activate
def test_get_max_revision_not_ok(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")
    repos = [Repos("SLES", "15SP3", arch)]
    project = "SUSE:Maintenance:12345"
    responses.add(responses.GET, url=SLES_URL, status=404)

    assert rp.get_max_revision(repos, arch, project) == 0
    assert "Submission skipped: RepoHash metadata not found at" in caplog.text


@responses.activate
def test_get_max_revision_with_submission_id_not_ok(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")
    repos = [Repos("SLES", "15SP3", arch)]
    project = "SUSE:Maintenance:12345"
    opts = RepoOptions(submission_id="git:1461")
    responses.add(responses.GET, url=SLES_URL, status=404)
    ret = rp.get_max_revision(repos, arch, project, options=opts)

    assert ret == 0
    assert "Submission skipped: RepoHash metadata not found at" in caplog.text


def test_merge_repohash() -> None:
    assert rp.merge_repohash(["a", "b", "c"]) == "c7e84e227cb118dbe1fa7d49b3e55fc3"


@responses.activate
def test_get_max_revision_slfo(mocker: MockerFixture) -> None:
    repos = [Repos("SLFO-Module", "1.1.99", arch)]
    project = "SLFO"
    product_version = "15.99"

    mocker.patch("openqabot.loader.repohash.gitea.get_product_name", return_value="SLES")
    url = "http://download.suse.de/ibs/SLFO/repo/repodata/repomd.xml"
    mock_compute_url = mocker.patch("openqabot.types.types.Repos.compute_url", return_value=url)
    responses.add(responses.GET, url=url, body=BASE_XML % "123")

    # Call with product_version
    opts = RepoOptions(product_version=product_version)
    ret = rp.get_max_revision(repos, arch, project, options=opts)
    assert ret == 123
    mock_compute_url.assert_called_with(ANY, "SLES", arch, project="SLFO")

    # Call without product_version
    ret = rp.get_max_revision(repos, arch, project)
    assert ret == 123
    mock_compute_url.assert_called_with(ANY, "SLES", arch, project="SLFO")

    # Call with product_name set
    opts = RepoOptions(product_name="SLES")
    ret = rp.get_max_revision(repos, arch, project, options=opts)
    assert ret == 123
    mock_compute_url.assert_called_with(ANY, "SLES", arch, project="SLFO")


@responses.activate
def test_get_max_revision_slfo_with_repo_version(mocker: MockerFixture) -> None:
    # repo with 4 elements: (product, version, arch, product_version)
    repos = [Repos("SLFO-Module", "1.1.99", arch, "15.99")]
    project = "SLFO"

    mocker.patch("openqabot.loader.repohash.gitea.get_product_name", return_value="SLES")
    url = "http://download.suse.de/ibs/SLFO/repo/repodata/repomd.xml"
    mock_compute_url = mocker.patch("openqabot.types.types.Repos.compute_url", return_value=url)
    responses.add(responses.GET, url=url, body=BASE_XML % "456")

    # Call without product_version in options, should take it from repo.product_version
    ret = rp.get_max_revision(repos, arch, project)
    assert ret == 456
    mock_compute_url.assert_called_with(ANY, "SLES", arch, project="SLFO")
