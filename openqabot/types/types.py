# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Common type definitions."""

from __future__ import annotations

from typing import NamedTuple

from openqabot.config import OBS_REPO_TYPE


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
        product = self.product.replace(":", ":/")
        version = self.version.replace(":", ":/")
        if project == "SLFO" or self.product.startswith("SUSE:SLFO"):
            start = f"{base}/{product}:/{version}/{OBS_REPO_TYPE}"
            if not product_name:
                return f"{start}/{path}"
            if not self.product_version:
                msg = f"Product version must be provided for {product_name}"
                raise ValueError(msg)
            return f"{start}/repo/{product_name}-{self.product_version}-{arch}/{path}"

        if self.product.startswith("openSUSE:"):
            return f"{base}/{product}:/{version}/{OBS_REPO_TYPE}/{path}"
        url_base = f"{base}/{project.replace(':', ':/')}" if project else base
        if self.product.startswith("openSUSE"):
            return f"{url_base}/SUSE_Updates_{self.product}_{self.version}/{path}"
        return f"{url_base}/SUSE_Updates_{self.product}_{self.version}_{arch}/{path}"


class ProdVer(NamedTuple):
    """Product and version details."""

    product: str
    version: str  # for SLFO it is the OBS project name; for others it is the product version
    product_version: str = ""  # if non-empty, "version" is the codestream version or OBS project

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


class ArchVer(NamedTuple):
    """Architecture and version details."""

    arch: str
    version: str  # the product version (and not the codestream version) if present in the context ArchVer is used


class OBSBinary(NamedTuple):
    """OBS binary coordinates."""

    project: str
    package: str
    repo: str
    arch: str
