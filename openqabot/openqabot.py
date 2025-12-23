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
from .loader.qem import get_incidents
from .openqa import openQAInterface

log = getLogger("bot.openqabot")


class OpenQABot:
    def __init__(self, args: Namespace) -> None:
        log.info("Starting bot schedule")
        self.dry = args.dry
        self.ignore_onetime = args.ignore_onetime
        self.token = {"Authorization": "Token " + args.token}
        self.incidents = get_incidents(self.token)
        log.info("Loaded %s incidents from QEM Dashboard", len(self.incidents))

        extrasettings = get_onearch(args.singlearch)

        self.workers = load_metadata(
            args.configs,
            aggregate=args.disable_aggregates,
            incidents=args.disable_incidents,
            extrasettings=extrasettings,
        )

        self.openqa = openQAInterface(args)
        self.ci = environ.get("CI_JOB_URL")

    def post_qem(self, data: dict[str, Any], api: str) -> None:
        if not self.openqa:
            log.warning(
                "Skipping dashboard update: No valid openQA configuration found for data: %s",
                data,
            )
            return

        res = put(api, headers=self.token, json=data)
        res_id = res.json().get("id", "No id?")
        log.info("Dashboard update successful: Status %s, Database ID %s", res.status_code, res_id)

    def post_openqa(self, data: dict[str, Any]) -> None:
        self.openqa.post_job(data)

    def __call__(self) -> int:
        log.info("Entering bot main loop")
        post: list[dict[str, Any]] = []
        for worker in self.workers:
            post += worker(self.incidents, self.token, self.ci, ignore_onetime=self.ignore_onetime)

        if self.dry:
            log.info("Dry run: Would trigger %d products in openQA", len(post))
            for job in post:
                log.info(job)
            log.info("Bot run completed")
            return 0

        log.info("Triggering %d products in openQA", len(post))

        def poster(job: dict[str, Any]) -> None:
            log.info("Triggering job: %s", job)
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
