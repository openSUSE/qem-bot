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

    def __init__(self, matched_iso: Match[str], pr_number: int) -> None:
        """Initialize IsoMatch from a regex match and PR number.

        Args:
            matched_iso (Match[str]): The regex match from the ISO filename.
            pr_number (int): The pull request number.

        """
        self.product = matched_iso.group("product")
        version = matched_iso.group("version")
        self.arch = matched_iso.group("arch")
        build_num = matched_iso.group("build")
        self.version = f"{version}:PR-{pr_number}"
        self.build = f"PR-{pr_number}-{build_num}:{self.product}-{version}"
