# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import Any

from .loader.gitea import get_incidents_from_open_prs, get_open_prs, make_token_header
from .loader.qem import update_incidents

log = getLogger("bot.giteasync")


class GiteaSync:
    def __init__(self, args: Namespace) -> None:
        self.dry: bool = args.dry
        self.fake_data: bool = args.fake_data
        self.dashboard_token: dict[str, str] = {"Authorization": "Token " + args.token}
        self.gitea_token: dict[str, str] = make_token_header(args.gitea_token)
        self.open_prs: list[Any] = get_open_prs(self.gitea_token, args.gitea_repo, self.fake_data, args.pr_number)
        log.info(
            "Loaded %i active PRs/incidents from %s",
            len(self.open_prs),
            args.gitea_repo,
        )
        self.incidents = get_incidents_from_open_prs(
            self.open_prs,
            self.gitea_token,
            not args.allow_build_failures,
            not args.consider_unrequested_prs,
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
        return update_incidents(self.dashboard_token, data, params={"type": "git"}, retry=self.retry)
