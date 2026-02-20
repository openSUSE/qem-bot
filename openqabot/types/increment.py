# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Types for handling a product increment."""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    import osc.core
    from openqabot.openqa import OpenQAResults

log = getLogger("bot.increment_approver")


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

    def log_no_jobs(self, params: list[dict[str, str]]) -> None:
        """Log that no relevant jobs were found."""
        log.info(
            "Skipping approval: There are no relevant jobs on openQA for %s",
            (" or ".join([self.string_with_params(param) for param in params]) if len(params) > 0 else {}),
        )

    def log_pending_jobs(self, pending_states: set[str]) -> None:
        """Log that some jobs are still pending."""
        log.info(
            "Skipping approval: Some jobs on openQA for %s are in pending states (%s)",
            self,
            ", ".join(sorted(pending_states)),
        )


class ApprovalStatus(NamedTuple):
    """Status of an approval request."""

    request: osc.core.Request
    ok_jobs: set[int]
    reasons_to_disapprove: list[str]

    def add(self, results: OpenQAResults) -> None:
        """Add jobs and reasons to the status."""
        self.ok_jobs.update(results.ok_jobs)
        self.reasons_to_disapprove.extend(results.generate_reasons_to_disapprove())
