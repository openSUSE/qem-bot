# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Types for handling a product increment."""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    import osc.core

log = getLogger("bot.increment_approver")


class BuildIdentifier(NamedTuple):
    """Identifier for a build."""

    build: str
    distri: str
    version: str

    @classmethod
    def from_job(cls, job: dict[str, Any]) -> BuildIdentifier:
        """Create a BuildIdentifier from an openQA job dictionary."""
        return cls(job["build"], job.get("distri", ""), job.get("version", ""))

    @classmethod
    def from_params(cls, params: dict[str, str]) -> BuildIdentifier:
        """Create a BuildIdentifier from scheduling parameters."""
        return cls(params["BUILD"], params["DISTRI"], params["VERSION"])


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

    def format_multi_build(self, params: list[dict[str, str]]) -> str:
        """Format a list of builds for logging."""
        build_strings = [self.string_with_params(param) for param in params]
        if len(build_strings) > 1:
            return "\n - " + "\n - ".join(build_strings)
        if build_strings:
            return build_strings[0]
        return "{}"

    def log_no_jobs(self, params: list[dict[str, str]]) -> None:
        """Log that no relevant jobs were found."""
        log.info("Skipping approval: There are no relevant jobs on openQA for %s", self.format_multi_build(params))

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
    devel: bool
    ok_jobs: set[int]
    reasons_to_disapprove: list[str]
    processed_jobs: set[tuple[str, str, str, str, str, str]]
    builds: set[BuildIdentifier]
    jobs: list[dict[str, Any]]

    def add(
        self,
        ok_jobs: set[int],
        reasons_to_disapprove: list[str],
        builds: set[BuildIdentifier],
        jobs: list[dict[str, Any]],
    ) -> None:
        """Add jobs and reasons to the status."""
        self.ok_jobs.update(ok_jobs)
        self.reasons_to_disapprove.extend(reasons_to_disapprove)
        self.builds.update(builds)
        self.jobs.extend(jobs)
