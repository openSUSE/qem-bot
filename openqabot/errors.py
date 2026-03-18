# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Custom exceptions."""


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


class PostOpenQAError(Error):
    """Raised when posting a job to openQA fails."""
