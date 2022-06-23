# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
class Error(Exception):
    pass


class NoRepoFoundError(Error):
    pass


class NoTestIssues(Error):
    pass


class EmptyChannels(Error):
    pass


class EmptyPackagesError(Error):
    pass


class SameBuildExists(Error):
    pass


class NoResultsError(Error):
    pass


class EmptySettings(Error):
    pass


class PostOpenQAError(Error):
    pass
