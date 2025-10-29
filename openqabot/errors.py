# Copyright SUSE LLC
# SPDX-License-Identifier: MIT


class Error(Exception):
    pass


class NoRepoFoundError(Error):
    pass


class NoTestIssuesError(Error):
    pass


class EmptyChannelsError(Error):
    pass


class EmptyPackagesError(Error):
    pass


class SameBuildExistsError(Error):
    pass


class NoResultsError(Error):
    pass


class EmptySettingsError(Error):
    pass


class PostOpenQAError(Error):
    pass
