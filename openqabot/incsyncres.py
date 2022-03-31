from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import Any, Dict, Sequence

from .loader.qem import get_active_incidents, get_incident_settings_data, post_job
from .openqa import openQAInterface
from .types import Data
from .utils import normalize_results

logger = getLogger("bot.incsyncres")


class IncResultsSync:
    def __init__(self, args: Namespace) -> None:
        self.dry = args.dry
        self.token = {"Authorization": f"Token {args.token}"}
        self.active = get_active_incidents(self.token)
        self.client = openQAInterface(args.openqa_instance)

    def __call__(self) -> int:

        incidents: Sequence[Data] = []

        for inc in self.active:
            try:
                incidents += get_incident_settings_data(self.token, inc)
            except ValueError:
                continue

        full = {}

        for d in incidents:
            full[d] = self.client.get_jobs(d)

        results = []
        for key, value in full.items():
            for v in value:
                if not "group" in v:
                    continue
                # TODO: check if is this right?
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
            logger.info("Posting jobs: %s" % pformat(r))
            if not self.dry and self.client:
                post_job(self.token, r)
            else:
                logger.info("Dry run -- data in dashboard untouched")

        logger.info("End of bot run")

        return 0

    @staticmethod
    def normalize_data(data: Data, job) -> Dict[str, Any]:
        ret = {}
        ret["job_id"] = job["id"]
        ret["incident_settings"] = data.settings_id
        ret["name"] = job["name"]
        ret["distri"] = data.distri
        ret["group_id"] = job["group_id"]
        ret["job_group"] = job["group"]
        ret["version"] = data.version
        ret["arch"] = data.arch
        ret["flavor"] = data.flavor
        ret["status"] = normalize_results(job["result"])
        ret["build"] = data.build
        ret["update_settings"] = None

        return ret
