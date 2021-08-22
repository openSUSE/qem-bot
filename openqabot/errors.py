class Error(Exception):
    pass


class NoRepoFoundError(Error):
    pass


class EmptyChannels(Error):
    pass

class EmptyPackagesError(Error):
    pass

class SameBuildExists(Error):
    pass


class NoResultsError(Error):
    pass
