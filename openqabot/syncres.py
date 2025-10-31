# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import Any, Dict

from . import ALLOW_DEVELOPMENT_GROUPS
from .loader.qem import post_job
from .openqa import openQAInterface
from .types import Data
from .utils import normalize_results

log = getLogger("bot.syncres")


class SyncRes:
    operation = "null"

    def __init__(self, args: Namespace) -> None:
        self.dry: bool = args.dry
        self.token: Dict[str, str] = {"Authorization": f"Token {args.token}"}
        self.client = openQAInterface(args)

    @classmethod
    def normalize_data(cls, data: Data, job: Dict[str, Any]) -> Dict[str, Any]:
        ret = {}
        ret["job_id"] = job["id"]
        ret["incident_settings"] = data.settings_id if cls.operation == "incident" else None
        ret["update_settings"] = data.settings_id if cls.operation == "aggregate" else None
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

    def _is_in_devel_group(self, data: Data) -> bool:
        return not ALLOW_DEVELOPMENT_GROUPS and (
            "Devel" in data["group"] or "Test" in data["group"] or self.client.is_devel_group(data["group_id"])
        )

    def filter_jobs(self, data: Dict[str, Any]) -> bool:
        """Filter out invalid/development jobs from results."""
        if "group" not in data:
            return False

        if data["clone_id"]:
            log.info("Job '%s' already has a clone, ignoring", data["clone_id"])
            return False

        if self._is_in_devel_group(data):
            log.info("Ignoring job '%s' in development group '%s'", data["id"], data["group"])
            return False

        return True

    def post_result(self, result: Dict[str, Any]) -> None:
        log.debug(
            "Posting results of %s job %s with status %s",
            self.operation,
            result["job_id"],
            result["status"],
        )
        log.debug("Full post data: %s", pformat(result))

        if not self.dry and self.client:
            post_job(self.token, result)
        else:
            log.info("Dry run -- data in dashboard untouched")
