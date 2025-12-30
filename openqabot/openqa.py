# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from argparse import Namespace
from functools import lru_cache
from itertools import starmap
from pprint import pformat
from typing import TYPE_CHECKING, Any

import requests
from openqa_client.client import OpenQA_Client
from openqa_client.exceptions import RequestError

from openqabot.config import DEVELOPMENT_PARENT_GROUP_ID, OPENQA_URL
from openqabot.utils import number_of_retries

from .errors import PostOpenQAError
from .loader.qem import update_job
from .types import Data

if TYPE_CHECKING:
    from urllib.parse import ParseResult


log = logging.getLogger("bot.openqa")


class openQAInterface:
    def __init__(self, args: Namespace) -> None:
        self.url: ParseResult = args.openqa_instance
        self.openqa = OpenQA_Client(server=self.url.netloc, scheme=self.url.scheme)
        self.retries = number_of_retries()
        user_agent = {"User-Agent": "python-OpenQA_Client/qem-bot/1.0.0"}
        self.openqa.session.headers.update(user_agent)
        self.qem_token: dict[str, str] = {"Authorization": f"Token {args.token}"}

    def __bool__(self) -> bool:
        """Return True only for the configured openQA instance.

        This is used for decide if the dashboard database should be updated or not
        """
        return self.url.netloc == OPENQA_URL

    def post_job(self, settings: dict[str, Any]) -> None:
        log.info(
            "openqa-cli api --host %s -X post isos %s",
            self.url.geturl(),
            " ".join(list(starmap("{}={}".format, settings.items()))),
        )
        try:
            self.openqa.openqa_request("POST", "isos", data=settings, retries=self.retries)
        except RequestError as e:
            log.exception("openQA API error: %s", e.args[-1])
            log.exception("Job POST failed for settings: %s", pformat(settings))
            raise PostOpenQAError from e
        except Exception as e:
            log.exception("Job POST failed for settings: %s", pformat(settings))
            raise PostOpenQAError from e

    def handle_job_not_found(self, job_id: int) -> None:
        log.info("Job %s not found on openQA, marking as obsolete on dashboard", job_id)
        update_job(self.qem_token, job_id, {"obsolete": True})

    def get_jobs(self, data: Data) -> list[dict[str, Any]]:
        log.info("Fetching openQA jobs for %s", pformat(data))
        param = {
            "scope": "relevant",
            "latest": "1",
            "flavor": data.flavor,
            "distri": data.distri,
            "build": data.build,
            "version": data.version,
            "arch": data.arch,
        }
        return self.openqa.openqa_request("GET", "jobs", param)["jobs"]

    @lru_cache(maxsize=512)
    def get_job_comments(self, job_id: int) -> list[dict[str, str]]:
        try:
            ret = self.openqa.openqa_request("GET", f"jobs/{job_id}/comments", retries=self.retries)
            return [{"text": c.get("text", "")} for c in ret]
        except RequestError as e:
            (_, _, status_code, *_) = e.args
            if status_code == 404:
                self.handle_job_not_found(job_id)
            else:
                log.exception("openQA API error when fetching comments for job %s", job_id)
        except requests.exceptions.RequestException:
            log.exception("openQA API error when fetching comments for job %s", job_id)
        return []

    @lru_cache(maxsize=256)
    def is_devel_group(self, groupid: int) -> bool:
        ret = self.openqa.openqa_request("GET", f"job_groups/{groupid}")
        # return True as safe option if ret = None
        return ret[0]["parent_id"] == DEVELOPMENT_PARENT_GROUP_ID if ret else True  # ID of Development Group

    @lru_cache(maxsize=256)
    def get_single_job(self, job_id: int) -> dict[str, Any] | None:
        try:
            return self.openqa.openqa_request("GET", f"jobs/{job_id}")["job"]
        except RequestError:
            log.exception("openQA API error when fetching job %s", job_id)
        return None

    @lru_cache(maxsize=256)
    def get_older_jobs(self, job_id: int, limit: int) -> dict:
        try:
            return self.openqa.openqa_request(
                "GET", f"/tests/{job_id}/ajax?previous_limit={limit}&next_limit=0", retries=self.retries
            )
        except RequestError:
            log.exception("openQA API error when fetching older jobs for job %s", job_id)
        return {"data": []}

    def get_scheduled_product_stats(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.openqa.openqa_request("GET", "isos/job_stats", params, retries=self.retries)
