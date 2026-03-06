# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Gitea loader specific type definitions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RepoConfig:
    """Configuration for OBS repository mirrors and product sets."""

    repo_type: str
    download_base_url: str
    obs_download_url: str
    repo_mirror_host: str
    obs_products: set[str] | None = None
