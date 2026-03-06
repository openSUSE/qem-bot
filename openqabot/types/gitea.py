# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Gitea loader specific type definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BuildTarget:
    """Build target information."""

    project: str
    arch: str
    product_name: str


@dataclass
class RepoConfig:
    """Repository configuration parameters."""

    repo_type: str
    download_base_url: str
    obs_download_url: str
    obs_products: set[str] | None = None
