# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import Dict

from .loader.qem import post_job
from .openqa import openQAInterface
from .types import Data
from .utils import normalize_results

logger = getLogger("bot.syncres")


class SyncRes:
    operation = "null"

    def __init__(self, args: Namespace) -> None:
        self.dry: bool = args.dry
        self.token: Dict[str, str] = {"Authorization": f"Token {args.token}"}
        self.client = openQAInterface(args.openqa_instance)

    @classmethod
    def normalize_data(cls, data: Data, job):
        ret = {}
        ret["job_id"] = job["id"]
        ret["incident_settings"] = (
            data.settings_id if cls.operation == "incident" else None
        )
        ret["update_settings"] = (
            data.settings_id if cls.operation == "aggregate" else None
        )
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

    def filter_jobs(self, data) -> bool:
        """Filter out invalid/development jobs from results"""

        if not "group" in data:
            return False

        if data["clone_id"]:
            logger.info("Clone job %s" % data["clone_id"])
            return False

        if self.client.is_devel_group(data["group_id"]):
            logger.info("Devel job %s in group %s" % (data["id"], data["group"]))
            return False

        return True

    def post_result(self, result):
        logger.info(
            "Posting results of %s job %s with status %s"
            % (self.operation, result["job_id"], result["status"])
        )
        logger.debug("Full post data: %s" % pformat(result))

        if not self.dry and self.client:
            post_job(self.token, result)
        else:
            logger.info("Dry run -- data in dashboard untouched")
