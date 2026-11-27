# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Maintenance update channel family: `SUSE:Updates:` channels."""

from __future__ import annotations

from .base import ChannelKind, ChannelType, Repos, register

EXPECTED_PART_LENGTH_WITH_ARCH = 3
EXPECTED_PART_LENGTH_NO_ARCH = 2
DEFAULT_ARCH = "x86_64"
# Channels of the development tools build service project carry no testable product
EXCLUDED_PRODUCTS = frozenset({"SLE-Module-Development-Tools-OBS"})


def _parse_channel(channel: str) -> Repos | None:
    """Parse `SUSE:Updates:<product>:<version>[:<arch>]` into its repository."""
    parts = channel.split(":")[2:]
    if len(parts) == EXPECTED_PART_LENGTH_WITH_ARCH and parts[0] not in EXCLUDED_PRODUCTS:
        return Repos(parts[0], parts[1], parts[2])
    if len(parts) == EXPECTED_PART_LENGTH_NO_ARCH:
        return Repos(parts[0], parts[1], DEFAULT_ARCH)
    return None


def _repo_url(repo: Repos, base: str, _product_name: str | None, arch: str, path: str, project: str | None) -> str:
    """Construct the repository URL of a maintenance channel."""
    url_base = f"{base}/{project.replace(':', ':/')}" if project else base
    return f"{url_base}/SUSE_Updates_{repo.product}_{repo.version}_{arch}/{path}"


KIND = register(
    ChannelKind(
        name="UPDATES",
        channel_type=ChannelType.UPDATES,
        prefixes=("SUSE:Updates",),
        parse=_parse_channel,
        repo_url=_repo_url,
    )
)
