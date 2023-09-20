# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from functools import lru_cache
import logging
from pprint import pformat
from urllib.parse import ParseResult

from openqa_client.client import OpenQA_Client
from openqa_client.exceptions import RequestError

from . import DEVELOPMENT_PARENT_GROUP_ID, OPENQA_URL
from .loader.qem import update_job
from .errors import PostOpenQAError
from .types import Data

log = logging.getLogger("bot.openqa")


class openQAInterface:
    def __init__(self, args) -> None:
        self.url: ParseResult = args.openqa_instance
        self.openqa = OpenQA_Client(server=self.url.netloc, scheme=self.url.scheme)
        self.retries = 3
        user_agent = {"User-Agent": "python-OpenQA_Client/qem-bot/1.0.0"}
        self.openqa.session.headers.update(user_agent)
        self.qem_token: Dict[str, str] = {"Authorization": f"Token {args.token}"}

    def __bool__(self) -> bool:
        """True only for the configured openQA instance, used for decide to update dashboard database or not"""
        return self.url.netloc == OPENQA_URL

    def post_job(self, settings) -> None:
        log.info(
            "openqa-cli api --host %s -X post isos %s"
            % (
                self.url.geturl(),
                " ".join(["%s=%s" % (k, v) for k, v in settings.items()]),
            )
        )
        try:
            self.openqa.openqa_request(
                "POST", "isos", data=settings, retries=self.retries
            )
        except RequestError as e:
            log.error("openQA returned %s" % e.args[-1])
            log.error("Post failed with {}".format(pformat(settings)))
            raise PostOpenQAError
        except Exception as e:
            log.exception(e)
            log.error("Post failed with {}".format(pformat(settings)))
            raise PostOpenQAError

    def handle_job_not_found(self, job_id: int):
        log.info(
            "Job %s not found in openQA, marking as obsolete on dashboard" % job_id
        )
        update_job(self.qem_token, job_id, {"obsolete": True})

    def get_jobs(self, data: Data):
        log.info("Getting openQA tests results for %s" % pformat(data))
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
        except Exception as e:
            log.exception(e)
            raise e
        return ret

    @lru_cache(maxsize=512)
    def get_job_comments(self, job_id: int):
        ret = []
        try:
            ret = self.openqa.openqa_request(
                "GET", "jobs/%s/comments" % job_id, retries=self.retries
            )
            ret = list(map(lambda c: {"text": c.get("text", "")}, ret))
        except Exception as e:
            (method, url, status_code, *other) = e.args
            if status_code == 404:
                self.handle_job_not_found(job_id)
            else:
                log.exception(e)
        return ret

    @lru_cache(maxsize=256)
    def is_devel_group(self, groupid: int) -> bool:
        ret = None

        try:
            ret = self.openqa.openqa_request("GET", f"job_groups/{groupid}")
        except Exception as e:
            log.exception(e)
            raise e

        # return True as safe option if ret = None
        return (
            ret[0]["parent_id"] == DEVELOPMENT_PARENT_GROUP_ID if ret else True
        )  # ID of Development Group
