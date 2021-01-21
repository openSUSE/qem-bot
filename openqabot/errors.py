class Error(Exception):
    pass


class NoRepoFoundError(Error):
    pass


class EmptyChannels(Error):
    pass


class SameBuildExists(Error):
    pass
