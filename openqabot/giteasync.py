# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import Any

from .loader.gitea import get_open_prs, get_submissions_from_open_prs, make_token_header
from .loader.qem import update_submissions

log = getLogger("bot.giteasync")


class GiteaSync:
    def __init__(self, args: Namespace) -> None:
        """Initialize the GiteaSync class."""
        self.dry: bool = args.dry
        self.fake_data: bool = args.fake_data
        self.dashboard_token: dict[str, str] = {"Authorization": "Token " + args.token}
        self.gitea_token: dict[str, str] = make_token_header(args.gitea_token)
        self.open_prs: list[Any] = get_open_prs(
            self.gitea_token,
            args.gitea_repo,
            dry=self.fake_data,
            number=args.pr_number,
        )
        log.info(
            "Loaded %d active PRs from %s",
            len(self.open_prs),
            args.gitea_repo,
        )
        self.submissions = get_submissions_from_open_prs(
            self.open_prs,
            self.gitea_token,
            only_successful_builds=not args.allow_build_failures,
            only_requested_prs=not args.consider_unrequested_prs,
            dry=self.fake_data,
        )
        self.retry = args.retry

    def __call__(self) -> int:
        data = self.submissions
        log.debug("Data for %d submissions: %s", len(data), pformat(data))
        if self.dry:
            log.info("Dry run: Would update QEM Dashboard data for %d submissions", len(data))
            return 0
        log.info("Syncing Gitea PRs to QEM Dashboard: Considering %d submissions", len(data))
        return update_submissions(self.dashboard_token, data, params={"type": "git"}, retry=self.retry)
