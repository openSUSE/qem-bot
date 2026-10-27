# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Custom exceptions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types.types import Data


class Error(Exception):
    """Base class for exceptions in this module."""


class NoRepoFoundError(Error):
    """Raised when no repository is found."""


class NoTestIssuesError(Error):
    """Raised when no test issues are found in configuration."""


class EmptyChannelsError(Error):
    """Raised when no channels are found for a submission."""


class EmptyPackagesError(Error):
    """Raised when no packages are found for a submission."""


class EmptyCommentError(Error):
    """Raised when generated comment is empty."""

    def __init__(self, submission: object) -> None:
        """Initialize with the submission that caused the empty comment."""
        super().__init__(f"Skipping empty comment for {submission}")


class SameBuildExistsError(Error):
    """Raised when a build with the same repohash already exists."""


class NoResultsError(Error):
    """Raised when no test results are found."""


class JobNotFoundError(Error):
    """Raised when a job is not found on openQA."""

    def __init__(self, job_id: int) -> None:
        """Initialize with the job ID that was not found."""
        super().__init__(f"Job {job_id} not found on openQA")


class AmbiguousApprovalStatusError(Error):
    """Raised when several request IDs pointing to the same openQA job."""


class LoaderQemError(Exception):
    """Raised when an error occurs in QEM loader."""


class SubmissionArgError(LoaderQemError):
    """Raised when a ``--submission`` argument cannot be parsed."""

    def __init__(self, raw: str, *, numeric: bool = False, positive: bool = False) -> None:
        """Build the error message for an invalid submission argument.

        With ``numeric`` set, report that the ``<id>`` part must be numeric;
        with ``positive`` set, that it must be greater than zero; otherwise
        report the expected ``<type>:<project>:<id>`` format.
        """
        if numeric:
            reason = "'<id>' must be numeric."
        elif positive:
            reason = "'<id>' must be greater than zero."
        else:
            reason = "Expected format '<type>:<project>:<id>'."
        message = f"Invalid submission ID {raw!r}. {reason}"
        super().__init__(message)


class FetchJobsError(Error):
    """Raised when fetching openQA jobs for a settings entry fails."""

    def __init__(self, data: Data, operation: str, cause: Exception) -> None:
        """Name the openQA query that failed so CI logs identify the affected submission."""
        target = (
            f"{data.submission_type}:{data.submission}" if data.submission else (data.product or data.submission_type)
        )
        super().__init__(
            f"Failed to fetch openQA jobs for {operation} {target}"
            f" settings {data.settings_id} ({data.distri} {data.version} {data.flavor} {data.arch}"
            f" build {data.build}): {cause}"
        )


class PostOpenQAError(Error):
    """Raised when posting a job to openQA fails."""


class DashboardError(Error):
    """Raised when a dashboard API request fails or returns unusable data."""
