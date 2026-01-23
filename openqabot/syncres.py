# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import Any

from .config import ALLOW_DEVELOPMENT_GROUPS, DEFAULT_SUBMISSION_TYPE
from .loader.qem import post_job
from .openqa import openQAInterface
from .types.types import Data
from .utils import normalize_results

log = getLogger("bot.syncres")


class SyncRes:
    operation = "null"

    def __init__(self, args: Namespace) -> None:
        self.dry: bool = args.dry
        self.token: dict[str, str] = {"Authorization": f"Token {args.token}"}
        self.client = openQAInterface(args)

    @classmethod
    def normalize_data(cls, data: Data, job: dict[str, Any]) -> dict[str, Any]:
        ret = {}
        ret["job_id"] = job["id"]
        ret["incident_settings"] = data.settings_id if cls.operation == "submission" else None
        ret["update_settings"] = data.settings_id if cls.operation == "aggregate" else None
        ret["submission_id"] = data.submission
        ret["submission_type"] = data.submission_type
        ret["name"] = job["name"]
        ret["distri"] = data.distri
        ret["group_id"] = job["group_id"]
        ret["job_group"] = job["group"]
        ret["version"] = data.version
        ret["arch"] = data.arch
        ret["flavor"] = data.flavor
        ret["status"] = normalize_results(job["result"])
        ret["build"] = data.build

        return ret

    def _normalize_data(self, key: Data, job: dict[str, Any]) -> dict[str, Any] | None:
        try:
            return self.normalize_data(key, job)
        except KeyError:
            return None

    def _is_in_devel_group(self, data: dict[str, Any]) -> bool:
        return not ALLOW_DEVELOPMENT_GROUPS and (
            "Devel" in data["group"] or "Test" in data["group"] or self.client.is_devel_group(data["group_id"])
        )

    def filter_jobs(self, data: dict[str, Any]) -> bool:
        """Filter out invalid/development jobs from results."""
        if "group" not in data:
            return False

        if data["clone_id"]:
            log.debug("Skipping job %s: Already has a clone %s", data["id"], data["clone_id"])
            return False

        if self._is_in_devel_group(data):
            log.debug("Skipping job %s: Belongs to development group '%s'", data["id"], data["group"])
            return False

        return True

    def post_result(self, result: dict[str, Any]) -> None:
        sub_id = ""
        if result.get("incident_settings"):
            sub_id = (
                f" for submission {result.get('submission_type', DEFAULT_SUBMISSION_TYPE)}:"
                f"{result.get('submission_id', 'unknown')}"
            )
        elif result.get("update_settings"):
            sub_id = " for aggregate"

        log.info(
            "Syncing %s job %s%s: Status %s",
            self.operation,
            result["job_id"],
            sub_id,
            result["status"],
        )
        log.debug("Full post data: %s", pformat(result))

        if not self.dry and self.client:
            post_job(self.token, result)
        else:
            log.info("Dry run: Skipping dashboard update")
