# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""ISO match information extracted from artifacts."""

from re import Match
from typing import Self


class IsoMatch:
    """Information extracted from a matched ISO filename."""

    product: str
    version: str
    arch: str
    build: str

    def __init__(self, product: str, version: str, build: str, arch: str = "x86_64") -> None:
        """Initialize the IsoMatch class."""
        self.product = product
        self.version = version
        self.arch = arch
        self.build = build

    @classmethod
    def from_regex_match(cls: type[Self], iso_match: Match[str], pr_number: int) -> Self:
        """Create an IsoMatch instance from a regex match."""
        product = iso_match.group("product")
        version = iso_match.group("version")
        arch = iso_match.group("arch")
        build_num = iso_match.group("build")
        version_str = f"{version}:PR-{pr_number}"
        build_str = f"PR-{pr_number}-{build_num}:{product}-{version}"
        return cls(product, version_str, build_str, arch)
