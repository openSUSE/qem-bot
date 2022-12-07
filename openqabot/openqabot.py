# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from logging import getLogger
from os import environ

from . import QEM_DASHBOARD
from .errors import PostOpenQAError
from .loader.config import get_onearch, load_metadata
from .loader.qem import get_incidents
from .openqa import openQAInterface
from .utils import retry3 as requests

log = getLogger("bot.openqabot")


class OpenQABot:
    def __init__(self, args: Namespace) -> None:
        log.info("Bot schedule starts now")
        self.dry = args.dry
        self.ignore_onetime = args.ignore_onetime
        self.token = {"Authorization": "Token " + args.token}
        self.incidents = get_incidents(self.token)
        log.info("%s incidents loaded from qem dashboard" % len(self.incidents))

        extrasettings = get_onearch(args.singlearch)

        self.workers = load_metadata(
            args.configs, args.disable_aggregates, args.disable_incidents, extrasettings
        )

        self.openqa = openQAInterface(args.openqa_instance)
        self.ci = environ.get("CI_JOB_URL")

    def post_qem(self, data, api) -> None:
        if not self.openqa:
            log.warning(
                "No valid openQA configuration specified: '%s' not posted to dashboard"
                % data
            )
            return

        url = QEM_DASHBOARD + api
        try:
            res = requests.put(url, headers=self.token, json=data)
            log.info(
                "Put to dashboard result %s, database id: %s"
                % (res.status_code, res.json().get("id", "No id?"))
            )
        except Exception as e:
            log.exception(e)
            raise e

    def post_openqa(self, data) -> None:
        self.openqa.post_job(data)

    def __call__(self):
        log.info("Starting bot mainloop")
        post = []
        for worker in self.workers:
            post += worker(self.incidents, self.token, self.ci, self.ignore_onetime)

        if self.dry:
            log.info("Would trigger %s products in openQA" % len(post))
            for job in post:
                log.info(job)

        else:
            log.info("Triggering %s products in openQA" % len(post))
            for job in post:
                log.info("Triggering %s" % str(job))
                try:
                    self.post_openqa(job["openqa"])
                except PostOpenQAError:
                    log.info("POST failed, not updating dashboard")
                    pass
                else:
                    self.post_qem(job["qem"], job["api"])

        log.info("End of bot run")

        return 0
