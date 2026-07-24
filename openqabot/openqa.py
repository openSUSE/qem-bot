# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""OpenQA Interface."""

from __future__ import annotations

import logging
from functools import lru_cache
from http import HTTPStatus
from itertools import batched
from pprint import pformat
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import requests
from openqa_client.client import OpenQA_Client
from openqa_client.exceptions import RequestError

import openqabot.config as config_module
from openqabot import config
from openqabot.utils import number_of_retries

from .errors import JobNotFoundError, PostOpenQAError
from .loader.qem import update_job

if TYPE_CHECKING:
    from urllib.parse import ParseResult

    from .types.types import Data


log = logging.getLogger("bot.openqa")

MAX_JOBS_PER_API_REQUEST = 200
ENRICH_KEYS = ("group_id", "group", "build", "distri", "version", "flavor", "arch", "name")


class OpenQAInterface:
    """Interface to openQA."""

    def __init__(self) -> None:
        """Initialize the OpenQAInterface class."""
        self.url: ParseResult = urlparse(config_module.settings.openqa_instance)
        self.dry: bool = config_module.settings.dry
        self.openqa = OpenQA_Client(server=self.url.netloc, scheme=self.url.scheme)
        self.openqa.session.verify = not config_module.settings.insecure
        self.retries = number_of_retries()
        user_agent = {"User-Agent": "python-OpenQA_Client/qem-bot/1.0.0"}
        self.openqa.session.headers.update(user_agent)

    def __bool__(self) -> bool:
        """Return True only for the configured openQA instance.

        This is used for decide if the dashboard database should be updated or not
        """
        return self.url.netloc == config.settings.main_openqa_domain

    def post_job(self, settings: dict[str, Any]) -> None:
        """Post a job to openQA with the given settings."""
        log.info(
            "openqa-cli api --host %s -X post isos %s",
            self.url.geturl(),
            " ".join(f"{k}={v}" for k, v in settings.items()),
        )
        if self.dry:
            log.info("OpenQA post_job skipped due dry run mode")
            return
        try:
            self.openqa.openqa_request("POST", "isos", data=settings, retries=self.retries)
        except RequestError as e:
            log.exception("openQA API error: %s", e.args[-1])
            log.exception("Job POST failed for settings: %s", pformat(settings))
            raise PostOpenQAError from e
        except Exception as e:
            log.exception("Job POST failed for settings: %s", pformat(settings))
            raise PostOpenQAError from e

    @staticmethod
    def handle_job_not_found(job_id: int) -> None:
        """Handle case where a job is not found on openQA."""
        log.info("Job %s not found on openQA, marking as obsolete on dashboard", job_id)
        update_job(job_id, {"obsolete": True})

    def get_jobs(self, data: Data) -> list[dict[str, Any]]:
        """Fetch openQA jobs matching the given criteria."""
        log.debug("Fetching openQA jobs for %s", pformat(data))
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

    @lru_cache(maxsize=512)  # ruff: ignore[cached-instance-method]
    def get_job_comments(self, job_id: int) -> list[dict[str, str]]:
        """Fetch comments for a specific job."""
        try:
            ret = self.openqa.openqa_request("GET", f"jobs/{job_id}/comments", retries=self.retries)
            return [{"text": c.get("text", "")} for c in ret]
        except RequestError as e:
            (_, _, status_code, *_) = e.args
            if status_code == HTTPStatus.NOT_FOUND:
                raise JobNotFoundError(job_id) from e
            log.exception("openQA API error when fetching comments for job %s", job_id)
        except requests.exceptions.RequestException:
            log.exception("openQA API error when fetching comments for job %s", job_id)
        return []

    @lru_cache(maxsize=256)  # ruff: ignore[cached-instance-method]
    def is_devel_group(self, groupid: int) -> bool:
        """Check if a job group is a development group."""
        ret = self.openqa.openqa_request("GET", f"job_groups/{groupid}")
        # return True as safe option if ret = None
        return (
            ret[0]["parent_id"] == config.settings.development_parent_group_id if ret else True
        )  # ID of Development Group

    @lru_cache(maxsize=256)  # ruff: ignore[cached-instance-method]
    def get_single_job(self, job_id: int) -> dict[str, Any] | None:
        """Fetch details for a single job."""
        try:
            return self.openqa.openqa_request("GET", f"jobs/{job_id}")["job"]
        except RequestError:
            log.exception("openQA API error when fetching job %s", job_id)
        return None

    def get_jobs_by_ids(self, job_ids: list[int]) -> list[dict[str, Any]]:
        """Fetch details for multiple jobs in batched API calls."""
        if not job_ids:
            return []

        results = []
        for chunk in batched(sorted(set(job_ids)), MAX_JOBS_PER_API_REQUEST, strict=False):
            try:
                res = self.openqa.openqa_request("GET", "jobs", {"ids": ",".join(map(str, chunk))})
                results.extend(res.get("jobs", []))
            except RequestError:
                log.exception("openQA API error when fetching multiple jobs")
        return results

    def is_in_devel_group(self, job: dict[str, Any]) -> bool:
        """Check if a job belongs to a development group."""
        if config.settings.allow_development_groups:
            return False

        group_name = job.get("group", "")
        group_id = job.get("group_id")

        if "Devel" in group_name or "Test" in group_name:
            return True

        return self.is_devel_group(group_id) if group_id else False

    @lru_cache(maxsize=256)  # ruff: ignore[cached-instance-method]
    def get_older_jobs(self, job_id: int, limit: int) -> dict:
        """Fetch older jobs for a specific job."""
        try:
            return self.openqa.openqa_request(
                "GET",
                f"/tests/{job_id}/ajax",
                {"previous_limit": limit, "next_limit": 0},
                retries=self.retries,
            )
        except RequestError:
            log.exception("openQA API error when fetching older jobs for job %s", job_id)
        return {"data": []}

    def get_scheduled_product_stats(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch scheduling statistics for a product."""
        return self.openqa.openqa_request("GET", "isos/job_stats", params, retries=self.retries)

    @lru_cache(maxsize=256)  # ruff: ignore[cached-instance-method]
    def get_job_group_info(self, group_id: int) -> dict[str, Any] | None:
        """Fetch job group details including description."""
        try:
            ret = self.openqa.openqa_request("GET", f"job_groups/{group_id}")
            if ret and len(ret) > 0:
                return ret[0]
        except RequestError:
            log.exception("openQA API error when fetching job group %s", group_id)
        return None

    def enrich_job_info(self, info: dict[str, Any], job_map: dict[int, dict[str, Any]]) -> dict[str, Any]:
        """Enrich job information with metadata, filtering out development jobs."""
        if not (ids := info.get("job_ids")):
            return info

        valid_ids = [i for i in ids if (job := job_map.get(int(i))) and not self.is_in_devel_group(job)]
        target_id = valid_ids[0] if valid_ids else ids[0]
        target_job = job_map.get(int(target_id))

        updated_info = info | {"job_ids": valid_ids or ids}
        if not target_job:
            return updated_info

        return updated_info | {k: target_job.get(k) for k in ENRICH_KEYS}

    def enrich_stats(self, stat: dict[str, Any], job_map: dict[int, dict[str, Any]]) -> dict[str, Any]:
        """Enrich all jobs in a scheduled product result with metadata."""
        return {
            status: {name: self.enrich_job_info(info, job_map) for name, info in jobs.items()}
            for status, jobs in stat.items()
        }
