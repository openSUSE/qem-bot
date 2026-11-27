# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""openSUSE channel family: `openSUSE-` products of the openSUSE distributions."""

from __future__ import annotations

from .base import ChannelKind, ChannelType, Repos, register


def _parse_channel(_channel: str) -> Repos | None:
    """Return nothing: openSUSE channels are built from metadata, never parsed from a submission."""
    return None


def _repo_url(repo: Repos, base: str, _product_name: str | None, _arch: str, path: str, project: str | None) -> str:
    """Construct the repository URL of an openSUSE product, which has no architecture in it."""
    url_base = f"{base}/{project.replace(':', ':/')}" if project else base
    return f"{url_base}/SUSE_Updates_{repo.product}_{repo.version}/{path}"


KIND = register(
    ChannelKind(
        name="OPENSUSE",
        channel_type=ChannelType.OPENSUSE,
        prefixes=("openSUSE",),
        parse=_parse_channel,
        repo_url=_repo_url,
    )
)
