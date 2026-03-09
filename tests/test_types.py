# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Tests for common type definitions."""

import pytest

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
