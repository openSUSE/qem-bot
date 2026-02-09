# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Common type definitions."""

from typing import NamedTuple


class Repos(NamedTuple):
    """Product and version information for a repository."""

    product: str
    version: str
    arch: str
    product_version: str = ""  # if non-empty, "version" is the codestream version


class ProdVer(NamedTuple):
    """Product and version details."""

    product: str
    version: str
    product_version: str = ""  # if non-empty, "version" is the codestream version


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
