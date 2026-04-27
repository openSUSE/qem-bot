# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""ISO match information extracted from artifacts."""

from re import Match


class IsoMatch:
    """Information extracted from a matched ISO filename."""

    product: str
    version: str
    arch: str
    build: str

    def __init__(self, iso_match: Match[str], pr_number: int) -> None:  # noqa: D107
        self.product = iso_match.group("product")
        version = iso_match.group("version")
        self.arch = iso_match.group("arch")
        build_num = iso_match.group("build")
        self.version = f"{version}:PR-{pr_number}"
        self.build = f"PR-{pr_number}-{build_num}:{self.product}-{version}"
