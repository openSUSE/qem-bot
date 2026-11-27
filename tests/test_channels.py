# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test the channel family registry."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from openqabot.types.channels import (
    ChannelType,
    Repos,
    channel_kind,
    filters_by_product,
    get_channel_type,
    kinds,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        ("SUSE:SLFO:1.3:PullRequest:10936:SLES:aarch64#16.1", "SLFO"),
        ("SLFO", "SLFO"),
        ("openSUSE-SLE:15.4", "OPENSUSE"),
        ("SUSE:Updates:SLES:15-SP5:x86_64", "UPDATES"),
        ("SLFOO:1.0", None),
        ("SUSE:SLE-15-SP4:Update:x86_64", None),
        ("home:okurz:branches:foo:x86_64", None),
        ("", None),
    ],
)
def test_channel_kind_of_channel_string(channel: str, expected: str | None) -> None:
    kind = channel_kind(channel)

    assert (kind.name if kind else None) == expected


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        ("SUSE:SLFO:1.3", ChannelType.SLFO),
        ("SLFO:project#15.99", ChannelType.SLFO),
        ("openSUSE-Leap", ChannelType.OPENSUSE),
        ("SLES", ChannelType.UPDATES),
        ("", ChannelType.UPDATES),
    ],
)
def test_get_channel_type_dispatches_through_the_registry(channel: str, expected: ChannelType) -> None:
    assert get_channel_type(channel) == expected


def test_configured_prefixes_replace_the_builtin_ones(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.config.settings.channel_kinds", {"SLFO": ("SUSE:SLFO2",)})

    assert get_channel_type("SUSE:SLFO2:1.3") is ChannelType.SLFO
    assert get_channel_type("SUSE:SLFO:1.3") is ChannelType.UPDATES


def test_configured_prefixes_of_an_absent_family_keep_the_builtin_ones(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.config.settings.channel_kinds", {"SLFO": ("SUSE:SLFO",)})

    assert get_channel_type("openSUSE-SLE:15.4") is ChannelType.OPENSUSE


def test_unknown_channel_family_is_ignored_with_a_warning(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="bot.types.channels")
    mocker.patch("openqabot.config.settings.channel_kinds", {"SLF0": ("SUSE:SLF0",)})

    kinds()
    kinds()

    assert [record.message for record in caplog.records] == [
        "Unknown channel family SLF0 in channel_kinds, ignoring it"
    ]


def test_registered_families_cover_updates_slfo_and_opensuse() -> None:
    assert {kind.channel_type for kind in kinds()} == {ChannelType.UPDATES, ChannelType.SLFO, ChannelType.OPENSUSE}


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
    kind = channel_kind(channel)

    assert kind is not None
    assert kind.parse(channel) == expected


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        ("SUSE:Updates:SLES:15-SP5:x86_64", Repos("SLES", "15-SP5", "x86_64")),
        ("SUSE:Updates:SLES:15-SP5", Repos("SLES", "15-SP5", "x86_64")),
        ("SUSE:Updates:SLE-Module-Development-Tools-OBS:15:x86_64", None),
        ("SUSE:Updates:SLES", None),
    ],
)
def test_update_channel_parsing(channel: str, expected: Repos | None) -> None:
    kind = channel_kind(channel)

    assert kind is not None
    assert kind.parse(channel) == expected


def test_open_suse_channels_are_never_parsed_from_a_submission() -> None:
    kind = channel_kind("openSUSE-SLE:15.4")

    assert kind is not None
    assert kind.parse("openSUSE-SLE:15.4") is None
    assert kind.repo_url(
        Repos("openSUSE-SLE", "15.4", "x86_64"), "base", None, "x86_64", "repodata/repomd.xml", None
    ) == ("base/SUSE_Updates_openSUSE-SLE_15.4/repodata/repomd.xml")


@pytest.mark.parametrize(
    ("channel", "expected"),
    [
        pytest.param("SUSE:Updates:SLES:15-SP5:x86_64", False),
        pytest.param("openSUSE-SLE:15.4", False),
        pytest.param("SUSE:SLFO:1.3:PullRequest:10936:SLES", True),
        pytest.param("SLES", False),
    ],
)
def test_families_that_select_their_repositories_by_product(channel: str, *, expected: bool) -> None:
    assert filters_by_product(channel) is expected


def test_slfo_family_reports_the_product_of_a_subproject() -> None:
    kind = channel_kind("SUSE:SLFO:1.3:PullRequest:10936:SLES")

    assert kind is not None
    assert kind.product_of("1.3:PullRequest:10936:SLES") == "SLES"
    assert not kind.product_of("1.3")
