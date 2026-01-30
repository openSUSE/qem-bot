# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Submission fixtures."""

from __future__ import annotations

from typing import Any

from openqabot.config import DEFAULT_SUBMISSION_TYPE
from openqabot.types.submission import Submission
from openqabot.types.types import ArchVer


class MockSubmission(Submission):
    """A flexible mock implementation of Submission class for testing."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the MockSubmission class."""
        self.id = kwargs.get("id", 0)
        self.staging = kwargs.get("staging", False)
        self.livepatch = kwargs.get("livepatch", False)
        self.packages = kwargs.get("packages", ["pkg"])
        self.rrid = kwargs.get("rrid")
        self.revisions = kwargs.get("revisions", {})
        self.project = kwargs.get("project", "")
        self.ongoing = kwargs.get("ongoing", True)
        self.type = kwargs.get("type", DEFAULT_SUBMISSION_TYPE)
        self.embargoed = kwargs.get("embargoed", False)
        self.channels = kwargs.get("channels", [])
        self.rr = kwargs.get("rr")
        self.priority = kwargs.get("priority")
        self.arch_filter = kwargs.get("arch_filter")
        self.emu = kwargs.get("emu", False)
        self.rev_fallback_value = kwargs.get("rev_fallback_value")
        self.contains_package_value = kwargs.get("contains_package_value")
        self.compute_revisions_value = kwargs.get("compute_revisions_value", True)

    def compute_revisions_for_product_repo(
        self,
        product_repo: list[str] | str | None,
        product_version: str | None,
        limit_archs: set[str] | None = None,
    ) -> bool:
        _ = (product_repo, product_version, limit_archs)
        return self.compute_revisions_value

    def revisions_with_fallback(self, arch: str, ver: str) -> int | None:
        if self.rev_fallback_value is not None:
            return self.rev_fallback_value
        if isinstance(self.revisions, dict):
            return self.revisions.get(ArchVer(arch, ver))
        return None

    def contains_package(self, requires: list[str]) -> bool:
        if self.contains_package_value is not None:
            return self.contains_package_value
        return any(p.startswith(tuple(requires)) for p in self.packages)
