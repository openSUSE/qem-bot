# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor, wait
from logging import getLogger
from os import environ
from typing import Any

from openqabot.dashboard import put

from .errors import PostOpenQAError
from .loader.config import get_onearch, load_metadata
from .loader.qem import get_submissions
from .openqa import openQAInterface

log = getLogger("bot.openqabot")


class OpenQABot:
    def __init__(self, args: Namespace) -> None:
        log.info("Starting bot schedule")
        self.dry = args.dry
        self.ignore_onetime = args.ignore_onetime
        self.token = {"Authorization": "Token " + args.token}
        self.submissions = get_submissions(self.token)
        log.info("Loaded %s submissions from QEM Dashboard", len(self.submissions))

        for sub in self.submissions:
            sub.log_skipped()

        extrasettings = get_onearch(args.singlearch)

        self.workers = load_metadata(
            args.configs,
            aggregate=args.disable_aggregates,
            submissions=args.disable_submissions,
            extrasettings=extrasettings,
        )

        self.openqa = openQAInterface(args)
        self.ci = environ.get("CI_JOB_URL")

    def post_qem(self, data: dict[str, Any], api: str) -> None:
        if not self.openqa:
            log.warning("Skipping dashboard update: No valid openQA configuration found for data: %s", data)
            return

        res = put(api, headers=self.token, json=data)
        res_id = res.json().get("id", "unknown")
        log.info("Dashboard update successful for %s: Status %s, Database ID %s", api, res.status_code, res_id)

    def post_openqa(self, data: dict[str, Any]) -> None:
        self.openqa.post_job(data)

    def __call__(self) -> int:
        log.info("Entering bot main loop")
        post = [
            p
            for w in self.workers
            for p in w(self.submissions, self.token, self.ci, ignore_onetime=self.ignore_onetime)
        ]

        log.info("Triggering %d products in openQA", len(post))

        def poster(job: dict[str, Any]) -> None:
            if self.dry:
                log.info("Would trigger job with details from dashboard: %s", job)
                return
            log.info("Triggering job with details from dashboard: %s", job)
            try:
                self.post_openqa(job["openqa"])
            except PostOpenQAError:
                log.info("Skipping dashboard update: Job post failed")
            else:
                self.post_qem(job["qem"], job["api"])

        with ThreadPoolExecutor() as executor:
            wait([executor.submit(poster, job) for job in post])
        log.info("Bot run completed")
        return 0
