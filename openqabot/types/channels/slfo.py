# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""SLFO channel family: OBS project names and scmsync URLs to product names."""

from __future__ import annotations

import re

PROJECT_PRODUCT_REGEX = re.compile(r".*:PullRequest:\d+:(.*)")
SCMSYNC_REGEX = re.compile(r".*/products/(.*)#([\d\.]{2,6})$")


def get_product_name(obs_project: str) -> str:
    """Extract product name from an OBS project name."""
    product_match = PROJECT_PRODUCT_REGEX.search(obs_project)
    return product_match.group(1) if product_match else ""


def get_product_name_and_version_from_scmsync(scmsync_url: str) -> tuple[str, str]:
    """Extract product name and version from an scmsync URL."""
    m = SCMSYNC_REGEX.search(scmsync_url)
    return (m.group(1), m.group(2)) if m else ("", "")
