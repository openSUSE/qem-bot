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


class SameBuildExistsError(Error):
    """Raised when a build with the same repohash already exists."""


class NoResultsError(Error):
    """Raised when no test results are found."""


class EmptySettingsError(Error):
    """Raised when settings are empty."""


class PostOpenQAError(Error):
    """Raised when posting a job to openQA fails."""
