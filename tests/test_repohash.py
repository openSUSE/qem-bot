# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging

import pytest
import requests
from requests import ConnectionError, HTTPError  # noqa: A004

import openqabot.loader.repohash as rp
import responses
from openqabot.errors import NoRepoFoundError

BASE_XML = '<repomd xmlns="http://linux.duke.edu/metadata/repo" xmlns:rpm="http://linux.duke.edu/metadata/rpm"><revision>%s</revision></repomd>'
SLES = BASE_XML % "256"
PROJECT = "SUSE:Maintenance:12345"


@responses.activate
def test_get_max_revison_manager_aarch64() -> None:
    repos = [("SLE-Module-SUSE-Manager-Server", "4.1")]
    arch = "aarch64"

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, PROJECT)


@responses.activate
def test_get_max_revison_opensuse() -> None:
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
def test_get_max_revison_3() -> None:
    add_sles_sled_response(BASE_XML % "257")
    ret = rp.get_max_revision(repos, arch, PROJECT)
    assert ret == 257


@responses.activate
def test_get_max_revison_connectionerror(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")
    add_sles_sled_response(requests.ConnectionError("Failed"))

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, PROJECT)

    assert "not found -- skipping incident" in caplog.records[0].msg
    assert "Maintenance:/12345" in caplog.records[0].args[0]


@responses.activate
def test_get_max_revison_httperror(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")
    add_sles_sled_response(requests.HTTPError("Failed"))

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, PROJECT)

    assert "not found -- skipping incident" in caplog.records[0].msg


@responses.activate
def test_get_max_revison_xmlerror(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")
    add_sles_sled_response("<invalid>")

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, PROJECT)

    assert "not found -- skipping incident" in caplog.records[0].msg


@responses.activate
def test_get_max_revison_empty_xml(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")
    add_sles_sled_response("<invalid></invalid>")

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, PROJECT)


@responses.activate
def test_get_max_revison_exception(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")
    add_sles_sled_response(BufferError("other error"))
    with pytest.raises(BufferError):
        rp.get_max_revision(repos, arch, PROJECT)


def test_merge_repohash() -> None:
    assert rp.merge_repohash(["a", "b", "c"]) == "c7e84e227cb118dbe1fa7d49b3e55fc3"
