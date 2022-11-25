import logging

import openqabot.loader.repohash as rp
import openqabot.loader.repohash
import pytest
import responses
from openqabot.errors import NoRepoFoundError
from requests import ConnectionError, HTTPError

BASE_XML = '<repomd xmlns="http://linux.duke.edu/metadata/repo" xmlns:rpm="http://linux.duke.edu/metadata/rpm"><revision>%s</revision></repomd>'


@responses.activate
def test_get_max_revison_manager_aarch64():

    repos = [("SLE-Module-SUSE-Manager-Server", "4.1")]
    project = "SUSE:Maintenance:12345"
    arch = "aarch64"

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, project)


@responses.activate
def test_get_max_revison_opensuse():

    repos = [("openSUSE-SLE", "4.1")]
    project = "SUSE:Maintenance:12345"
    arch = "aarch64"
    opensuse = BASE_XML % "256"

    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_openSUSE-SLE_4.1/repodata/repomd.xml",
        body=opensuse,
    )
    ret = rp.get_max_revision(repos, arch, project)
    assert ret == 256


@responses.activate
def test_get_max_revison_3():

    repos = [("SLES", "15SP3"), ("SLED", "15SP3")]
    project = "SUSE:Maintenance:12345"
    arch = "x86_64"

    sles = BASE_XML % "256"
    sled = BASE_XML % "257"
    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLES_15SP3_x86_64/repodata/repomd.xml",
        body=sles,
    )
    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLED_15SP3_x86_64/repodata/repomd.xml",
        body=sled,
    )

    ret = rp.get_max_revision(repos, arch, project)

    assert ret == 257


@responses.activate
def test_get_max_revison_connectionerror(caplog):

    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")

    repos = [("SLES", "15SP3"), ("SLED", "15SP3")]
    project = "SUSE:Maintenance:12345"
    arch = "x86_64"

    sles = BASE_XML % "256"
    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLES_15SP3_x86_64/repodata/repomd.xml",
        body=sles,
    )
    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLED_15SP3_x86_64/repodata/repomd.xml",
        body=ConnectionError("Failed"),
    )

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, project)

    assert (
        caplog.records[0].msg
        == "http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLED_15SP3_x86_64/repodata/repomd.xml not found -- skip incident"
    )


@responses.activate
def test_get_max_revison_httperror(caplog):

    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")

    repos = [("SLES", "15SP3"), ("SLED", "15SP3")]
    project = "SUSE:Maintenance:12345"
    arch = "x86_64"

    sles = BASE_XML % "256"
    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLES_15SP3_x86_64/repodata/repomd.xml",
        body=sles,
    )
    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLED_15SP3_x86_64/repodata/repomd.xml",
        body=HTTPError("Failed"),
    )

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, project)

    assert (
        caplog.records[0].msg
        == "http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLED_15SP3_x86_64/repodata/repomd.xml not found -- skip incident"
    )


@responses.activate
def test_get_max_revison_xmlerror(caplog):

    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")

    repos = [("SLES", "15SP3"), ("SLED", "15SP3")]
    project = "SUSE:Maintenance:12345"
    arch = "x86_64"

    sles = BASE_XML % "256"
    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLES_15SP3_x86_64/repodata/repomd.xml",
        body=sles,
    )
    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLED_15SP3_x86_64/repodata/repomd.xml",
        body="<invalid>",
    )

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, project)

    assert (
        caplog.records[0].msg
        == "http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLED_15SP3_x86_64/repodata/repomd.xml not found -- skip incident"
    )


@responses.activate
def test_get_max_revison_empty_xml(caplog):

    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")

    repos = [("SLES", "15SP3"), ("SLED", "15SP3")]
    project = "SUSE:Maintenance:12345"
    arch = "x86_64"

    sles = BASE_XML % "256"
    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLES_15SP3_x86_64/repodata/repomd.xml",
        body=sles,
    )
    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLED_15SP3_x86_64/repodata/repomd.xml",
        body="<invalid></invalid>",
    )

    with pytest.raises(NoRepoFoundError):
        rp.get_max_revision(repos, arch, project)


@responses.activate
def test_get_max_revison_exception(caplog):

    caplog.set_level(logging.DEBUG, logger="bot.loader.repohash")

    repos = [("SLES", "15SP3"), ("SLED", "15SP3")]
    project = "SUSE:Maintenance:12345"
    arch = "x86_64"

    sles = BASE_XML % "256"
    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLES_15SP3_x86_64/repodata/repomd.xml",
        body=sles,
    )
    responses.add(
        responses.GET,
        url="http://download.suse.de/ibs/SUSE:/Maintenance:/12345/SUSE_Updates_SLED_15SP3_x86_64/repodata/repomd.xml",
        body=Exception("Failed"),
    )

    with pytest.raises(Exception):
        rp.get_max_revision(repos, arch, project)

    assert "Failed" == str(caplog.records[0].msg)


def test_merge_repohash():
    assert "c7e84e227cb118dbe1fa7d49b3e55fc3" == rp.merge_repohash(["a", "b", "c"])
