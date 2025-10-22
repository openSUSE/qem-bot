# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor, wait
from logging import getLogger
from os import environ
from typing import Any, Dict, List

from openqabot.dashboard import put

from .errors import PostOpenQAError
from .loader.config import get_onearch, load_metadata
from .loader.qem import get_incidents
from .openqa import openQAInterface

log = getLogger("bot.openqabot")


class OpenQABot:
    def __init__(self, args: Namespace) -> None:
        log.info("Bot schedule starts now")
        self.dry = args.dry
        self.ignore_onetime = args.ignore_onetime
        self.token = {"Authorization": "Token " + args.token}
        self.incidents = get_incidents(self.token)
        log.info("%s incidents loaded from qem dashboard", len(self.incidents))

        extrasettings = get_onearch(args.singlearch)

        self.workers = load_metadata(
            args.configs,
            aggregate=args.disable_aggregates,
            incidents=args.disable_incidents,
            extrasettings=extrasettings,
        )

        self.openqa = openQAInterface(args)
        self.ci = environ.get("CI_JOB_URL")

    def post_qem(self, data: Dict[str, Any], api: str) -> None:
        if not self.openqa:
            log.warning(
                "No valid openQA configuration specified: '%s' not posted to dashboard",
                data,
            )
            return

        res = put(api, headers=self.token, json=data)
        log.info("Put to dashboard result %s, database id: %s", res.status_code, res.json().get("id", "No id?"))

    def post_openqa(self, data: Dict[str, Any]) -> None:
        self.openqa.post_job(data)

    def __call__(self) -> int:
        log.info("Starting bot mainloop")
        post: List[Dict[str, Any]] = []
        for worker in self.workers:
            post += worker(self.incidents, self.token, self.ci, ignore_onetime=self.ignore_onetime)

        if self.dry:
            log.info("Would trigger %d products in openQA", len(post))
            for job in post:
                log.info(job)

        else:
            log.info("Triggering %d products in openQA", len(post))

            def poster(job: Dict[str, Any]) -> None:
                log.info("Triggering %s", job)
                try:
                    self.post_openqa(job["openqa"])
                except PostOpenQAError:
                    log.info("POST failed, not updating dashboard")
                else:
                    self.post_qem(job["qem"], job["api"])

            with ThreadPoolExecutor() as executor:
                wait([executor.submit(poster, job) for job in post])

        log.info("End of bot run")

        return 0
