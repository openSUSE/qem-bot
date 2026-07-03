# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Common type definitions."""

from __future__ import annotations

from enum import Enum, auto
from typing import TYPE_CHECKING, NamedTuple

from openqabot.config import OBS_REPO_TYPE

if TYPE_CHECKING:
    from openqabot.loader.triggerconfig import TriggerConfig
    from openqabot.types.isomatch import IsoMatch


class ChannelType(Enum):
    """Enumeration of channel types."""

    UPDATES = auto()
    SLFO = auto()
    OPENSUSE = auto()


_CHANNEL_PREFIX_MAP = {
    "SUSE:SLFO": ChannelType.SLFO,
    "SLFO": ChannelType.SLFO,
    "openSUSE": ChannelType.OPENSUSE,
}


def get_channel_type(product: str) -> ChannelType:
    """Determine the channel type based on the product string."""
    return next(
        (v for k, v in _CHANNEL_PREFIX_MAP.items() if product.startswith(k)),
        ChannelType.UPDATES,
    )


class Repos(NamedTuple):
    """Product and version information for a repository."""

    product: str
    version: str  # for SLFO it is the OBS project name; for others it is the product version
    arch: str
    product_version: str = ""  # if non-empty, "version" is the codestream version or OBS project

    def compute_url(
        self,
        base: str,
        product_name: str | None = None,
        arch: str | None = None,
        path: str = "repodata/repomd.xml",
        project: str | None = None,
    ) -> str:
        """Construct the repository URL."""
        arch = arch or self.arch
        if get_channel_type(self.product) == ChannelType.SLFO or project == "SLFO":
            product = self.product.replace(":", ":/")
            version = self.version.replace(":", ":/")
            start = f"{base}/{product}:/{version}/{OBS_REPO_TYPE}"
            if not product_name:
                return f"{start}/{path}"
            if not self.product_version:
                msg = f"Product version must be provided for {product_name}"
                raise ValueError(msg)
            return f"{start}/repo/{product_name}-{self.product_version}-{arch}/{path}"

        url_base = f"{base}/{project.replace(':', ':/')}" if project else base
        if get_channel_type(self.product) == ChannelType.OPENSUSE:
            return f"{url_base}/SUSE_Updates_{self.product}_{self.version}/{path}"
        return f"{url_base}/SUSE_Updates_{self.product}_{self.version}_{arch}/{path}"


class ProdVer(NamedTuple):
    """Product and version details."""

    product: str
    version: str  # for SLFO it is the OBS project name; for others it is the product version
    product_version: str = ""  # if non-empty, "version" is the codestream version or OBS project

    @classmethod
    def from_issue_channel(cls, issue: str) -> ProdVer:
        """Create a ProdVer from an issue channel string like 'SLFO:project#version'."""
        channel_parts = issue.split(":")
        version_parts = channel_parts[1].split("#")
        return cls(channel_parts[0], version_parts[0], version_parts[1] if len(version_parts) > 1 else "")

    def compute_url(
        self,
        base: str,
        product_name: str,
        arch: str,
        path: str = "repodata/repomd.xml",
        project: str | None = "SLFO",
    ) -> str:
        """Construct the repository URL for a Gitea submission."""
        # This is a bit redundant but keeps ProdVer functional until it can be fully removed
        repo = Repos(self.product, self.version, arch, self.product_version)
        return repo.compute_url(base, product_name, arch, path, project)


class Data(NamedTuple):
    """Common data for dashboard and openQA."""

    submission: int
    submission_type: str
    settings_id: int
    flavor: str
    arch: str
    distri: str
    version: str
    build: str
    product: str

    @classmethod
    def from_trigger_config_and_matched_iso(
        cls, trigger_config: TriggerConfig, matched_iso: IsoMatch, submission_id: int
    ) -> Data:
        """Generate Data object from TriggerConfig and IsoMatch."""
        return cls(
            submission_id,
            "git",
            0,
            trigger_config.flavor,
            matched_iso.arch,
            trigger_config.distri,
            matched_iso.version,
            matched_iso.build,
            matched_iso.product,
        )


class ArchVer(NamedTuple):
    """Architecture and version details."""

    arch: str
    version: str  # the product version (and not the codestream version) if present in the context ArchVer is used
