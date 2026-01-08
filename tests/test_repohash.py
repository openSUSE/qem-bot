# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from typing import Any, cast
from unittest.mock import ANY

import pytest
import requests
from pytest_mock import MockerFixture
from requests import ConnectionError, HTTPError  # noqa: A004

import openqabot.loader.repohash as rp
import responses
from openqabot.errors import NoRepoFoundError

BASE_XML = '<repomd xmlns="http://linux.duke.edu/metadata/repo" xmlns:rpm="http://linux.duke.edu/metadata/rpm"><revision>%s</revision></repomd>'
SLES = BASE_XML % "256"
PROJECT = "SUSE:Maintenance:12345"


@responses.activate
def test_get_max_revision_manager_aarch64() -> None:
    repos = [("SLE-Module-SUSE-Manager-Server", "4.1")]
    arch = "aarch64"

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, PROJECT)


@responses.activate
def test_get_max_revision_opensuse() -> None:
    repos = [("openSUSE-SLE", "4.1")]
    arch = "aarch64"
    opensuse = BASE_XML % "256"

    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_openSUSE-SLE_4.1/repodata/repomd.xml",
        body=opensuse,
    )
    ret = rp.get_max_revision(repos, arch, PROJECT)
    assert ret == 256


repos = [("SLES", "15SP3"), ("SLED", "15SP3")]
arch = "x86_64"


def add_sles_sled_response(sled_body: str | ConnectionError | HTTPError | BufferError) -> None:
    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLES_15SP3_x86_64/repodata/repomd.xml",
        body=SLES,
    )
    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLED_15SP3_x86_64/repodata/repomd.xml",
        body=sled_body,
    )


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

    assert "Submission skipped: RepoHash metadata not found at" in caplog.records[0].msg
    assert "Maintenance:/12345" in cast("str", cast("Any", caplog.records[0].args)[0])


@responses.activate
def test_get_max_revision_httperror(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.repohash")
    add_sles_sled_response(requests.HTTPError("Failed"))

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, PROJECT)

    assert "Submission skipped: RepoHash metadata not found at" in caplog.records[0].msg


@responses.activate
def test_get_max_revision_xmlerror(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.repohash")
    add_sles_sled_response("<invalid>")

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, PROJECT)

    assert "Submission skipped: RepoHash metadata not found at" in caplog.records[0].msg


@responses.activate
def test_get_max_revision_empty_xml(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.repohash")
    add_sles_sled_response("<invalid></invalid>")

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, PROJECT)

    assert "Submission skipped: RepoHash calculation failed, no revision tag found in %s" in caplog.records[0].msg


@responses.activate
def test_get_max_revision_exception(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")
    add_sles_sled_response(BufferError("other error"))
    with pytest.raises(BufferError):
        rp.get_max_revision(repos, arch, PROJECT)


@responses.activate
def test_get_max_revision_retry_error(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")
    repos = [("SLES", "15SP3")]
    arch = "x86_64"
    project = "SUSE:Maintenance:12345"

    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLES_15SP3_x86_64/repodata/repomd.xml",
        body=requests.exceptions.RetryError("Max retries exceeded"),
    )

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, project)


@responses.activate
def test_get_max_revision_not_ok(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")
    repos = [("SLES", "15SP3")]
    arch = "x86_64"
    project = "SUSE:Maintenance:12345"
    url = "http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLES_15SP3_x86_64/repodata/repomd.xml"
    responses.add(responses.GET, url=url, status=404)

    assert rp.get_max_revision(repos, arch, project) == 0
    assert "Submission skipped: RepoHash metadata not found at" in caplog.text


def test_merge_repohash() -> None:
    assert rp.merge_repohash(["a", "b", "c"]) == "c7e84e227cb118dbe1fa7d49b3e55fc3"


@responses.activate
def test_get_max_revision_slfo(mocker: MockerFixture) -> None:
    repos = [("SLFO-Module", "1.1.99")]
    arch = "x86_64"
    project = "SLFO"
    product_version = "15.99"

    mocker.patch("openqabot.loader.repohash.gitea.get_product_name", return_value="SLES")
    mock_compute_url = mocker.patch(
        "openqabot.loader.repohash.gitea.compute_repo_url",
        return_value="http://download.suse.de/ibs/SLFO/repo/repodata/repomd.xml",
    )
    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SLFO/repo/repodata/repomd.xml",
        body=BASE_XML % "123",
    )

    # Call with product_version
    ret = rp.get_max_revision(repos, arch, project, product_version=product_version)
    assert ret == 123
    mock_compute_url.assert_called_with(ANY, "SLES", ("SLFO-Module", "1.1.99", product_version), arch)

    # Call without product_version
    ret = rp.get_max_revision(repos, arch, project)
    assert ret == 123
    mock_compute_url.assert_called_with(ANY, "SLES", ("SLFO-Module", "1.1.99"), arch)

    # Call with product_name set
    ret = rp.get_max_revision(repos, arch, project, product_name="SLES")
    assert ret == 123
    mock_compute_url.assert_called_with(ANY, "SLES", ("SLFO-Module", "1.1.99"), arch)
