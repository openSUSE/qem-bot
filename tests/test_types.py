# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Tests for common type definitions."""

import re

import pytest

from openqabot.types.isomatch import IsoMatch
from openqabot.types.types import ChannelType, ProdVer, Repos, get_channel_type


@pytest.mark.parametrize(
    ("product", "expected"),
    [
        ("SUSE:SLFO:1.1", ChannelType.SLFO),
        ("SLFO", ChannelType.SLFO),
        ("openSUSE-SLE", ChannelType.OPENSUSE),
        ("openSUSE-Leap", ChannelType.OPENSUSE),
        ("SLES", ChannelType.UPDATES),
        ("SLE-Module-Basesystem", ChannelType.UPDATES),
        ("SomethingElse", ChannelType.UPDATES),
        ("", ChannelType.UPDATES),
    ],
)
def test_get_channel_type(product: str, expected: ChannelType) -> None:
    """Test get_channel_type() with various product strings."""
    assert get_channel_type(product) == expected


def test_prodver_from_issue_channel_with_product_version() -> None:
    """Parse issue channel with product version."""
    pv = ProdVer.from_issue_channel("SLFO:project#15.99")
    assert pv.product == "SLFO"
    assert pv.version == "project"
    assert pv.product_version == "15.99"


def test_prodver_from_issue_channel_without_product_version() -> None:
    """Parse issue channel without product version."""
    pv = ProdVer.from_issue_channel("SLES:15-SP3")
    assert pv.product == "SLES"
    assert pv.version == "15-SP3"
    assert not pv.product_version


def test_prodver_from_issue_channel_type() -> None:
    """Channel type can be derived from factory-created ProdVer."""
    assert get_channel_type(ProdVer.from_issue_channel("SLFO:x#1").product) == ChannelType.SLFO
    assert get_channel_type(ProdVer.from_issue_channel("SLES:15").product) == ChannelType.UPDATES
    assert get_channel_type(ProdVer.from_issue_channel("openSUSE-SLE:15.4").product) == ChannelType.OPENSUSE


def test_repos_compute_url_slfo_via_project_param() -> None:
    """project='SLFO' triggers SLFO URL path regardless of product string."""
    repo = Repos("SomeProduct", "1.2", "x86_64")
    url = repo.compute_url("base", path="repomd.xml", project="SLFO")
    assert url == "base/SomeProduct:/1.2/product/repomd.xml"


def test_repos_compute_url_opensuse() -> None:
    """OpenSUSE URL omits architecture."""
    repo = Repos("openSUSE-SLE", "15.4", "x86_64")
    url = repo.compute_url("base", path="repomd.xml")
    assert url == "base/SUSE_Updates_openSUSE-SLE_15.4/repomd.xml"


def test_repos_compute_url_updates() -> None:
    """SUSE Updates URL includes architecture."""
    repo = Repos("SLES", "15-SP3", "x86_64")
    url = repo.compute_url("base", path="repomd.xml")
    assert url == "base/SUSE_Updates_SLES_15-SP3_x86_64/repomd.xml"


def test_repos_compute_url_updates_with_project() -> None:
    """SUSE Updates URL with explicit project."""
    repo = Repos("SLES", "15-SP3", "x86_64")
    url = repo.compute_url("base", path="repomd.xml", project="SUSE:Maintenance:12345")
    assert url == "base/SUSE:/Maintenance:/12345/SUSE_Updates_SLES_15-SP3_x86_64/repomd.xml"


def test_isomatch_from_regex_match() -> None:
    """Test IsoMatch.from_regex_match classmethod."""
    pattern = re.compile(r"(?P<product>\w+)-(?P<version>[\d\.]+)-(?P<arch>\w+)-Build(?P<build>[\d\.]+)\.iso")
    match = pattern.match("SLES-15.5-x86_64-Build1.1.iso")
    assert match is not None
    isomatch = IsoMatch.from_regex_match(match, 123)
    assert isomatch.product == "SLES"
    assert isomatch.version == "15.5:PR-123"
    assert isomatch.arch == "x86_64"
    assert isomatch.build == "PR-123-1.1:SLES-15.5"


def test_isomatch_constructor() -> None:
    """Test IsoMatch init using raw values."""
    isomatch = IsoMatch("SLES", "15.5", "PR-123")
    assert isomatch.product == "SLES"
    assert isomatch.version == "15.5"
    assert isomatch.arch == "x86_64"
    assert isomatch.build == "PR-123"

    isomatch_custom_arch = IsoMatch("SLES", "15.5", "PR-123", arch="aarch64")
    assert isomatch_custom_arch.arch == "aarch64"
