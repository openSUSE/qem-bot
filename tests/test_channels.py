# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test the channel family registry."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

from openqabot.types.channels import ChannelType, Repos, channel_kind, get_channel_type, kinds


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        ("SUSE:SLFO:1.3:PullRequest:10936:SLES:aarch64#16.1", "SLFO"),
        ("SLFO", "SLFO"),
        ("openSUSE-SLE:15.4", "OPENSUSE"),
        ("SUSE:Updates:SLES:15-SP5:x86_64", "UPDATES"),
        ("SLFOO:1.0", "UPDATES"),
        ("", "UPDATES"),
    ],
)
def test_channel_kind_of_channel_string(channel: str, expected: str) -> None:
    assert channel_kind(channel).name == expected


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        ("SUSE:SLFO:1.3", ChannelType.SLFO),
        ("SLFO:project#15.99", ChannelType.SLFO),
        ("openSUSE-Leap", ChannelType.OPENSUSE),
        ("SLES", ChannelType.UPDATES),
    ],
)
def test_get_channel_type_dispatches_through_the_registry(channel: str, expected: ChannelType) -> None:
    assert get_channel_type(channel) == expected


def test_configured_prefixes_replace_the_builtin_ones(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.config.settings.channel_kinds", {"SLFO": ("SUSE:SLFO2",)})

    assert channel_kind("SUSE:SLFO2:1.3").name == "SLFO"
    assert channel_kind("SUSE:SLFO:1.3").name == "UPDATES"


def test_configured_prefixes_of_an_absent_family_keep_the_builtin_ones(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.config.settings.channel_kinds", {"SLFO": ("SUSE:SLFO",)})

    assert channel_kind("openSUSE-SLE:15.4").name == "OPENSUSE"


def test_kinds_are_ordered_from_specific_to_default() -> None:
    assert [kind.channel_type for kind in kinds()] == [
        ChannelType.OPENSUSE,
        ChannelType.SLFO,
        ChannelType.UPDATES,
    ]


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        (
            "SUSE:SLFO:1.3:PullRequest:10936:SLES:aarch64#16.1",
            Repos("SUSE:SLFO", "1.3:PullRequest:10936:SLES", "aarch64", "16.1"),
        ),
        ("SUSE:SLFO:Main:1.0:x86_64#products/SLFO", Repos("SUSE:SLFO", "Main:1.0", "x86_64", "products/SLFO")),
        ("SUSE:SLFO:1.0:x86_64", Repos("SUSE:SLFO", "1.0", "x86_64")),
        ("SUSE:SLFO:1.0", None),
    ],
)
def test_slfo_channel_parsing(channel: str, expected: Repos | None) -> None:
    assert channel_kind(channel).parse(channel) == expected


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        ("SUSE:Updates:SLES:15-SP5:x86_64", Repos("SLES", "15-SP5", "x86_64")),
        ("SUSE:Updates:SLES:15-SP5", Repos("SLES", "15-SP5", "x86_64")),
        ("SUSE:Updates:SLE-Module-Development-Tools-OBS:15:x86_64", None),
        ("SUSE:Updates:SLES", None),
        ("openSUSE-Leap:15.4", None),
    ],
)
def test_update_channel_parsing(channel: str, expected: Repos | None) -> None:
    assert channel_kind(channel).parse(channel) == expected


def test_open_suse_channels_are_never_parsed_from_a_submission() -> None:
    kind = channel_kind("openSUSE-SLE:15.4")

    assert kind.parse("openSUSE-SLE:15.4") is None
    assert kind.repo_url(
        Repos("openSUSE-SLE", "15.4", "x86_64"), "base", None, "x86_64", "repodata/repomd.xml", None
    ) == ("base/SUSE_Updates_openSUSE-SLE_15.4/repodata/repomd.xml")


def test_families_without_product_selection_report_no_product() -> None:
    assert not channel_kind("SUSE:Updates:SLES:15-SP5:x86_64").product_of("SUSE:Updates:SLES")
    assert channel_kind("SUSE:Updates:SLES:15-SP5:x86_64").filters_by_product is False


def test_slfo_family_selects_repositories_by_product() -> None:
    kind = channel_kind("SUSE:SLFO:1.3:PullRequest:10936:SLES")

    assert kind.filters_by_product is True
    assert kind.product_of("1.3:PullRequest:10936:SLES") == "SLES"
