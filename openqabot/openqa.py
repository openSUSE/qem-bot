# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from functools import lru_cache
import logging
from pprint import pformat
from urllib.parse import ParseResult

from openqa_client.client import OpenQA_Client
from openqa_client.exceptions import RequestError

from .types import Data

logger = logging.getLogger("bot.openqa")


class openQAInterface:
    def __init__(self, instance: ParseResult) -> None:
        self.url = instance
        self.openqa = OpenQA_Client(server=self.url.netloc, scheme=self.url.scheme)

    def __bool__(self) -> bool:
        """True only for OSD, used for decide to update dashboard database or not"""
        return self.url.netloc == "openqa.suse.de"

    def post_job(self, settings) -> None:
        logger.info(
            "openqa-cli api --host %s -X post isos %s"
            % (
                self.url.geturl(),
                " ".join(["%s=%s" % (k, v) for k, v in settings.items()]),
            )
        )
        try:
            self.openqa.openqa_request("POST", "isos", data=settings, retries=3)
        except RequestError as e:
            logger.error("openQA returned %s" % e[-1])
            logger.error("Post failed with {}".format(pformat(settings)))
        except Exception as e:
            logger.exception(e)
            logger.error("Post failed with {}".format(pformat(settings)))

    def get_jobs(self, data: Data):
        logger.info("Getting openQA tests results for %s" % pformat(data))
        param = {}
        param["scope"] = "relevant"
        param["latest"] = "1"
        param["flavor"] = data.flavor
        param["distri"] = data.distri
        param["build"] = data.build
        param["version"] = data.version
        param["arch"] = data.arch

        ret = None
        try:
            ret = self.openqa.openqa_request("GET", "jobs", param)["jobs"]
        # TODO: correct handling
        except Exception as e:
            logger.exception(e)
            raise e
        return ret

    @lru_cache(maxsize=256)
    def is_devel_group(self, groupid: int) -> bool:
        ret = None

        try:
            ret = self.openqa.openqa_request("GET", f"job_groups/{groupid}")
        except Exception as e:
            logger.exception(e)
            raise e

        # return True as safe option if ret = None
        return ret[0]["name"] == "Development" if ret else True
