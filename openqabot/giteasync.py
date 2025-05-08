# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import Any, Dict, List

from .loader.qem import update_incidents
from .loader.gitea import get_open_prs, get_incidents_from_open_prs

log = getLogger("bot.giteasync")


class GiteaSync:
    def __init__(self, args: Namespace) -> None:
        self.dry: bool = args.dry
        self.fake_data: bool = args.fake_data
        self.dashboard_token: Dict[str, str] = {"Authorization": "Token " + args.token}
        self.gitea_token: Dict[str, str] = {
            "Authorization": "token " + args.gitea_token
        }
        self.open_prs: List[Any] = get_open_prs(
            self.gitea_token, args.gitea_repo, self.fake_data
        )
        self.incidents = get_incidents_from_open_prs(
            self.open_prs,
            self.gitea_token,
            not args.allow_build_failures,
            self.fake_data,
        )
        self.retry = args.retry

    def __call__(self) -> int:
        log.info("Starting to sync incidents from Gitea to dashboard")

        data = self.incidents
        log.info("Updating info about %s incidents", str(len(data)))
        log.debug("Data: %s", pformat(data))

        if self.dry:
            log.info("Dry run, nothing synced")
            return 0
        return update_incidents(self.dashboard_token, data, retry=self.retry)
