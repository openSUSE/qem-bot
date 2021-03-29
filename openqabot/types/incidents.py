from logging import getLogger
from typing import List

import requests

from openqabot.pc_helper import request_get

from . import ProdVer, Repos
from ..errors import SameBuildExists
from .baseconf import BaseConf
from .incident import Incident

logger = getLogger("bot.types.incidents")


class Incidents(BaseConf):
    def __init__(self, product: str, settings, config) -> None:
        super().__init__(product, settings, config)
        self.flavors = self.normalize_repos(config["FLAVOR"])

    def __repr__(self):
        return f"<Incidents product: {self.product}>"

    @staticmethod
    def normalize_repos(config):
        ret = {}
        for flavor, data in config.items():
            ret[flavor] = {}
            for key, value in data.items():
                if key == "issues":
                    ret[flavor][key] = {
                        template: ProdVer(channel.split(":")[0], channel.split(":")[1])
                        for template, channel in value.items()
                    }
                else:
                    ret[flavor][key] = value

        return ret

    @staticmethod
    def _is_sheduled_job(token: str, inc: Incident, arch: str, flavor: str) -> bool:
        try:
            jobs = requests.get(
                f"http://qam2.suse.de:4000/api/incident_settings/{inc.id}",
                headers=token,
            ).json()
        except Exception as e:
            # TODO: ....
            logger.exception(e)

        if not jobs:
            return False

        for job in jobs:
            if (
                job["flavor"] == flavor
                and job["arch"] == arch
                and job["settings"]["REPOHASH"] == inc.revisions[arch]
            ):
                return True

        return False

    def __call__(self, incidents: List[Incident], token):

        DOWNLOAD_BASE = "https://download.suse.de/ibs/SUSE:/Maintenance:/"
        BASE_PRIO = 50
        ret = []

        for flavor, data in self.flavors.items():
            for arch in data["archs"]:
                for inc in incidents:
                    full_post = {}
                    full_post["api"] = "/api/incident_settings"
                    full_post["qem"] = {}
                    full_post["openqa"] = {}
                    full_post["openqa"].update(self.settings)
                    full_post["qem"]["incident"] = inc.id
                    full_post["openqa"]["ARCH"] = arch
                    full_post["qem"]["arch"] = arch
                    full_post["openqa"]["FLAVOR"] = flavor
                    full_post["qem"]["flavor"] = flavor
                    full_post["openqa"]["VERSION"] = self.settings["VERSION"]
                    full_post["qem"]["version"] = self.settings["VERSION"]
                    full_post["openqa"]["DISTRI"] = self.settings["DISTRI"]
                    full_post["openqa"]["_ONLY_OBSOLETE_SAME_BUILD"] = "1"
                    full_post["openqa"]["_OBSOLETE"] = "1"

                    if "packages" in data:
                        if not inc.contains_package(data["packages"]):
                            continue

                    if inc.livepatch:
                        if flavor != "Server-DVD-Incidents-Kernel":
                            continue
                        else:
                            full_post["openqa"]["KGRAFT"] = "1"

                    if inc.azure:
                        full_post["openqa"]["AZURE"] = "1"

                    full_post["openqa"]["BUILD"] = f":{inc.id}:{inc.packages[0]}"
                    # old bot used variable "REPO_ID"
                    try:
                        full_post["openqa"]["REPOHASH"] = inc.revisions[arch]
                    except KeyError:
                        logger.debug("Incident %s dont have % arch" % (inc.id, arch))
                        continue

                    # TODO: Public Cloud settings...
                    #
                    #

                    channels_set = set()
                    issue_dict = {}

                    for issue, channel in data["issues"].items():
                        f_channel = Repos(channel.product, channel.version, arch)
                        if f_channel in inc.channels:
                            issue_dict[issue] = inc
                            channels_set.add(f_channel)

                    if not issue_dict:
                        logger.debug(
                            "No channels in %s for %s on %s" % (inc.id, flavor, arch)
                        )
                        continue

                    if "required_issues" in data:
                        if set(issue_dict.keys()).isdisjoint(data["required_issues"]):
                            continue

                    if self._is_sheduled_job(token, inc, arch, flavor):
                        logger.debug(
                            "NOT SHEDULE: Flavor: %s , incident %s , arch %s  - exists in openQA "
                            % (flavor, inc.id, arch)
                        )
                        continue

                    for key, value in issue_dict.items():
                        full_post["openqa"][key] = str(value.id)

                    repos = (
                        f"{DOWNLOAD_BASE}{inc.id}/SUSE_Updates_{'_'.join(chan)}"
                        for chan in channels_set
                    )
                    full_post["openqa"]["INCIDENT_REPO"] = ",".join(repos)

                    full_post["qem"]["withAggregate"] = True
                    aggregate_job = data.get("aggregate_job", True)

                    if not aggregate_job:
                        pos = set(data.get("aggregate_check_true", []))
                        neg = set(data.get("aggregate_check_false", []))

                        if pos and not pos.isdisjoint(full_post["openqa"].keys()):
                            full_post["qem"]["withAggregate"] = False
                            logger.info("Aggregate not needed for incident %s" % inc.id)
                        if neg and neg.isdisjoint(full_post["openqa"].keys()):
                            full_post["qem"]["withAggregate"] = False 
                            logger.info("Aggregate not needed for incident %s" % inc.id)
                        if not (neg and pos):
                            full_post["qem"]["withAggregate"] = False 

                    delta_prio = data.get("override_priority", 0)

                    if delta_prio:
                        delta_prio -= 50
                    else:
                        if flavor.endswith("Minimal"):
                            delta_prio -= 5
                        if not inc.staging:
                            delta_prio += 10
                        if inc.emu:
                            delta_prio = -20
                        # override default prio only for specific jobs
                        if delta_prio:
                            full_post["openqa"]["_PRIORITY"] = BASE_PRIO + delta_prio

                        # add custom vars to job settings
                    if "params_expand" in data:
                        full_post["openqa"].update(data["params_expand"])

                    full_post["qem"]["settings"] = full_post["openqa"]

                    ret.append(full_post)
        return ret
