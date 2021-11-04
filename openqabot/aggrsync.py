from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor, as_completed
from logging import getLogger
from pprint import pformat
from typing import Dict

from .errors import EmptySettings
from .loader.config import read_products
from .loader.qem import get_aggregate_settings_data, post_job
from .openqa import openQAInterface
from .types import Data
from .utils import normalize_results

logger = getLogger("bot.aggrsync")


class AggregateResultsSync:
    def __init__(self, args: Namespace) -> None:
        self.dry: bool = args.dry
        self.token: Dict[str, str] = {"Authorization": f"Token {args.token}"}
        self.product = read_products(args.configs)
        self.client = openQAInterface(args.openqa_instance)

    def __call__(self) -> int:

        update_setting = []
        for product in self.product:
            try:
                update_setting += get_aggregate_settings_data(self.token, product)
            except EmptySettings as e:
                logger.info(e)
                continue

        job_results = {}
        with ThreadPoolExecutor() as executor:
            future_j = {
                executor.submit(self.client.get_jobs, f): f for f in update_setting
            }
            for future in as_completed(future_j):
                job_results[future_j[future]] = future.result()

        results = []
        for key, values in job_results.items():
            for v in values:
                if not "group" in v:
                    continue
                if v["clone_id"]:
                    logger.info("Clone job %s" % v["clone_id"])
                    continue

                if "Devel" in v["group"] or "Test" in v["group"]:
                    logger.info("Devel job %s in group %s" % (v["id"], v["group"]))
                    continue

                if "Timo" in v["group"]:
                    logger.info(
                        "Devel job %s in group %s -- thx. Timo" % (v["id"], v["group"])
                    )
                    continue

                if "Leap" in v["group"]:
                    logger.info(
                        "Devel job %s in group %s -- Leap jobs arent in good state"
                        % (v["id"], v["group"])
                    )
                    continue

                try:
                    r = self.normalize_data(key, v)
                except KeyError:
                    continue

                results.append(r)

        for r in results:
            logger.debug("Updating aggregate job results: %s" % pformat(r))

            if not self.dry and self.client:
                post_job(self.token, r)
            else:
                logger.info("Dry run -- data not updated in dashboard")

        return 0

    @staticmethod
    def normalize_data(data: Data, job):
        ret = {}
        ret["job_id"] = job["id"]
        ret["incident_settings"] = None
        ret["name"] = job["name"]
        ret["distri"] = data.distri
        ret["group_id"] = job["group_id"]
        ret["job_group"] = job["group"]
        ret["version"] = data.version
        ret["arch"] = data.arch
        ret["flavor"] = data.flavor
        ret["status"] = normalize_results(job["result"])
        ret["build"] = data.build
        ret["update_settings"] = data.settings_id

        return ret
