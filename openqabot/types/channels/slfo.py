# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""SLFO channel family: `SUSE:SLFO:` channels and the OBS project names behind them."""

from __future__ import annotations

import re

from openqabot.config import settings

from .base import ChannelKind, ChannelType, Repos, register

PROJECT_PRODUCT_REGEX = re.compile(r".*:PullRequest:\d+:(.*)")
SCMSYNC_REGEX = re.compile(r".*/products/(.*)#([\d\.]{2,6})$")
EXPECTED_PART_LENGTH = 3


def get_product_name(obs_project: str) -> str:
    """Extract product name from an OBS project name."""
    product_match = PROJECT_PRODUCT_REGEX.search(obs_project)
    return product_match.group(1) if product_match else ""


def get_product_name_and_version_from_scmsync(scmsync_url: str) -> tuple[str, str]:
    """Extract product name and version from an scmsync URL."""
    m = SCMSYNC_REGEX.search(scmsync_url)
    return (m.group(1), m.group(2)) if m else ("", "")


def _parse_channel(channel: str) -> Repos | None:
    """Parse `SUSE:SLFO:<version>:<subproject>:<arch>#<product version>` into its repository."""
    parts = channel.split(":")
    if len(parts) <= EXPECTED_PART_LENGTH:
        return None
    arch, _, product_version = parts[-1].partition("#")
    return Repos(":".join(parts[:2]), ":".join(parts[2:-1]), arch, product_version)


def _repo_url(repo: Repos, base: str, product_name: str | None, arch: str, path: str, _project: str | None) -> str:
    """Construct the repository URL of a product published by an OBS project."""
    start = f"{base}/{repo.product.replace(':', ':/')}:/{repo.version.replace(':', ':/')}/{settings.obs_repo_type}"
    if not product_name:
        return f"{start}/{path}"
    if not repo.product_version:
        msg = f"Product version must be provided for {product_name}"
        raise ValueError(msg)
    return f"{start}/repo/{product_name}-{repo.product_version}-{arch}/{path}"


KIND = register(
    ChannelKind(
        name="SLFO",
        channel_type=ChannelType.SLFO,
        prefixes=("SUSE:SLFO", "SLFO"),
        parse=_parse_channel,
        repo_url=_repo_url,
        product_of=get_product_name,
        filters_by_product=True,
    )
)
