# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Types for handling a product increment."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    import osc.core


class BuildInfo(NamedTuple):
    """Information about a build."""

    distri: str
    product: str
    version: str
    flavor: str
    arch: str
    build: str

    def __str__(self) -> str:
        """Return a string representation of the BuildInfo."""
        return f"{self.product}v{self.version} build {self.build}@{self.arch} of flavor {self.flavor}"

    def string_with_params(self, params: dict[str, str]) -> str:
        """Return a string representation of the build with overridden parameters."""
        version = params.get("VERSION", self.version)
        flavor = params.get("FLAVOR", self.flavor)
        arch = params.get("ARCH", self.arch)
        build = params.get("BUILD", self.build)
        return f"{self.product}v{version} build {build}@{arch} of flavor {flavor}"


class ApprovalStatus(NamedTuple):
    """Status of an approval request."""

    request: osc.core.Request
    ok_jobs: set[int]
    reasons_to_disapprove: list[str]

    def add(self, ok_jobs: set[int], reasons_to_disapprove: list[str]) -> None:
        """Add jobs and reasons to the status."""
        self.ok_jobs.update(ok_jobs)
        self.reasons_to_disapprove.extend(reasons_to_disapprove)
