from collections import defaultdict
from datetime import date
from itertools import chain
from logging import getLogger
from typing import Dict

import requests

from . import ProdVer, Repos
from ..errors import SameBuildExists
from ..loader.repohash import merge_repohash
from ..pc_helper import (
    apply_pc_tools_image,
    apply_publiccloud_pint_image,
    apply_publiccloud_regex,
)
from .baseconf import BaseConf

logger = getLogger("bot.types.aggregate")

class Aggregate(BaseConf):
    def __init__(self, product: str, settings, config) -> None:
        super().__init__(product, settings, config)
        self.flavor = config["FLAVOR"]
        self.archs = config["archs"]
        self.onetime = config.get("onetime", False)
        self.test_issues = self.normalize_repos(config)

    @staticmethod
    def normalize_repos(config) -> Dict[str, ProdVer]:
        return {
            key: ProdVer(value.split(":")[0], value.split(":")[1])
            for key, value in config["test_issues"].items()
        }

    def __repr__(self):
        return f"<Aggregate product: {self.product}>"

    @staticmethod
    def get_buildnr(repohash: str, old_repohash: str, cur_build: str) -> str:
        today = date.today().strftime("%Y%m%d")
        build = today

        if cur_build.startswith(today) and repohash == old_repohash:
            raise SameBuildExists

        if cur_build.startswith(today):
            counter = int(cur_build.split("-")[-1]) + 1
        else:
            counter = 1

        return f"{build}-{counter}"

    def __call__(self, incidents, token, ignore_onetime=False):
        ret = []

        for arch in self.archs:
            full_post = {}
            full_post["openqa"] = {}
            full_post["qem"] = {}
            full_post["qem"]["incidents"] = []
            full_post["qem"]["settings"] = {}
            full_post["api"] = "/api/update_settings"

            test_incidents = defaultdict(list)
            
            # only testing queue and not livepatch
            valid_incidents = [i for i in incidents if not any((i.livepatch, i.staging))]
            for issue, template in self.test_issues.items():
                for inc in valid_incidents:
                    if Repos(template.product, template.version, arch) in inc.channels:
                        test_incidents[issue].append(inc)

            full_post["openqa"]["REPOHASH"] = merge_repohash(
                sorted(
                    set(
                        str(inc) for inc in chain.from_iterable(test_incidents.values())
                    )
                )
            )

            try:
                old_jobs = requests.get(
                    "http://dashboard.qam.suse.de/api/update_settings",
                    params={"product": self.product, "arch": arch},
                    headers=token,
                ).json()
            except Exception as e:
                # TODO: valid exceptions ...
                logger.exception(e)
                old_jobs = None

            old_repohash = old_jobs[0].get("repohash", "") if old_jobs else ""
            old_build = old_jobs[0].get("build", "") if old_jobs else ""

            try:
                full_post["openqa"]["BUILD"] = self.get_buildnr(
                    full_post["openqa"]["REPOHASH"], old_repohash, old_build
                )
            except SameBuildExists:
                logger.info(
                    "For %s aggreagate on %s there is existing build"
                    % (self.product, arch)
                )
                continue

            if not ignore_onetime and (
                self.onetime and full_post["openqa"]["BUILD"].split("-")[-1] != "1"
            ):
                continue

            settings = self.settings.copy()

            # if set, we use this query to detect latest public cloud tools image which used for running
            # all public cloud related tests in openQA
            if "PUBLICCLOUD_TOOLS_IMAGE_QUERY" in settings:
                settings = apply_pc_tools_image(settings)
                if settings["PC_TOOLS_IMAGE_BASE"] is None:
                    logger.error(
                        f"Failed to query latest publiccloud tools image using {settings['PUBLICCLOUD_TOOLS_IMAGE_QUERY']}"
                    )
                    continue

            # parse Public-Cloud image REGEX if present
            if "PUBLIC_CLOUD_IMAGE_REGEX" in settings:
                settings = apply_publiccloud_regex(settings)
                if settings["PUBLIC_CLOUD_IMAGE_LOCATION"] is None:
                    logger.error(
                        f"No publiccloud image found for {settings['PUBLIC_CLOUD_IMAGE_REGEX']}"
                    )
                    continue
            # parse Public-Cloud pint query if present
            if "PUBLICCLOUD_PINT_QUERY" in settings:
                settings = apply_publiccloud_pint_image(settings)
                if settings["PUBLIC_CLOUD_IMAGE_ID"] is None:
                    logger.error(
                        f"No publiccloud image fetched from pint for for {settings['PUBLICCLOUD_PINT_QUERY']}"
                    )
                    continue

            full_post["openqa"].update(settings)
            full_post["openqa"]["FLAVOR"] = self.flavor
            full_post["openqa"]["ARCH"] = arch
            full_post["openqa"]["_OBSOLETE"] = 1

            for template, issues in test_incidents.items():
                full_post["openqa"][template] = ",".join(str(x) for x in issues)
            for issues in test_incidents.values():
                full_post["qem"]["incidents"] += issues

            full_post["qem"]["incidents"] = [
                str(inc) for inc in set(full_post["qem"]["incidents"])
            ]
            if not full_post["qem"]["incidents"]:
                continue

            full_post["qem"]["settings"] = full_post["openqa"]
            full_post["qem"]["repohash"] = full_post["openqa"]["REPOHASH"]
            full_post["qem"]["build"] = full_post["openqa"]["BUILD"]
            full_post["qem"]["arch"] = full_post["openqa"]["ARCH"]
            full_post["qem"]["product"] = self.product

            # add to ret
            ret.append(full_post)

        return ret
