# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from collections import defaultdict
from datetime import date
from itertools import chain
from logging import getLogger
from typing import Any, Dict, List, Optional

from . import ProdVer, Repos
from .. import DOWNLOAD_BASE, QEM_DASHBOARD
from ..errors import NoTestIssues, SameBuildExists
from ..loader.repohash import merge_repohash
from ..pc_helper import apply_pc_tools_image, apply_publiccloud_pint_image
from ..dashboard import get_json
from .baseconf import BaseConf
from .incident import Incident


log = getLogger("bot.types.aggregate")


class Aggregate(BaseConf):
    def __init__(self, product: str, settings, config) -> None:
        super().__init__(product, settings, config)
        self.flavor = config["FLAVOR"]
        self.archs = config["archs"]
        self.onetime = config.get("onetime", False)
        self.test_issues = self.normalize_repos(config)

    @staticmethod
    def normalize_repos(config):
        try:
            repos = {
                key: ProdVer(value.split(":")[0], value.split(":")[1])
                for key, value in config["test_issues"].items()
            }
        except KeyError:
            raise NoTestIssues

        return repos

    def __repr__(self):
        return f"<Aggregate product: {self.product}>"

    @staticmethod
    def get_buildnr(repohash: str, old_repohash: str, build: str) -> str:
        today = date.today().strftime("%Y%m%d")

        if build.startswith(today) and repohash == old_repohash:
            raise SameBuildExists

        counter = int(build.split("-")[-1]) + 1 if build.startswith(today) else 1
        return f"{today}-{counter}"

    def __call__(
        self,
        incidents: List[Incident],
        token: Dict[str, str],
        ci_url: Optional[str],
        ignore_onetime: bool = False,
    ) -> List[Dict[str, Any]]:
        ret = []

        for arch in self.archs:
            full_post: Dict["str", Any] = {}
            full_post["openqa"] = {}
            full_post["qem"] = {}
            full_post["qem"]["incidents"] = []
            full_post["qem"]["settings"] = {}
            full_post["api"] = "api/update_settings"
            if ci_url:
                full_post["openqa"]["__CI_JOB_URL"] = ci_url

            test_incidents = defaultdict(list)
            test_repos = defaultdict(list)

            # Temporary workaround for applying the correct architecture on jobs, which use a helper VM
            issues_arch = self.settings.get("TEST_ISSUES_ARCH", arch)

            # only testing queue and not livepatch
            valid_incidents = list()
            for i in incidents:
                if not any((i.livepatch, i.staging)):
                    # if filtering embargoed updates is on
                    if self.filter_embargoed(self.flavor) and i.embargoed:
                        # we take ONLY non-embargoed updates
                        log.debug(
                            "Incident %s is skipped because filtering \
                                      embargoed is on and incident has embargoed True",
                            i.id,
                        )
                    # if filtering embargoed updates is off we ignoring this field
                    else:
                        valid_incidents.append(i)
            for issue, template in self.test_issues.items():
                for inc in valid_incidents:
                    if (
                        Repos(template.product, template.version, issues_arch)
                        in inc.channels
                    ):
                        test_incidents[issue].append(inc)

            for issue, incs in test_incidents.items():
                tmpl = issue.replace("ISSUES", "REPOS")
                for inc in incs:
                    if self.test_issues[issue].product.startswith("openSUSE"):
                        test_repos[tmpl].append(
                            f"{DOWNLOAD_BASE}{inc}/SUSE_Updates_{self.test_issues[issue].product}_{self.test_issues[issue].version}/"
                        )
                    else:
                        test_repos[tmpl].append(
                            f"{DOWNLOAD_BASE}{inc}/SUSE_Updates_{self.test_issues[issue].product}_{self.test_issues[issue].version}_{issues_arch}/"
                        )

            full_post["openqa"]["REPOHASH"] = merge_repohash(
                sorted(
                    set(
                        str(inc) for inc in chain.from_iterable(test_incidents.values())
                    )
                )
            )

            try:
                old_jobs = get_json(
                    "api/update_settings",
                    params={"product": self.product, "arch": arch},
                    headers=token,
                )
            except Exception as e:  # pylint: disable=broad-except
                log.exception(e)
                old_jobs = None

            old_repohash = old_jobs[0].get("repohash", "") if old_jobs else ""
            old_build = old_jobs[0].get("build", "") if old_jobs else ""

            try:
                full_post["openqa"]["BUILD"] = self.get_buildnr(
                    full_post["openqa"]["REPOHASH"], old_repohash, old_build
                )
            except SameBuildExists:
                log.info(
                    "For %s aggreagate on %s there is existing build",
                    self.product,
                    arch,
                )
                continue

            if not ignore_onetime and (
                self.onetime and full_post["openqa"]["BUILD"].split("-")[-1] != "1"
            ):
                continue

            settings = self.settings.copy()

            # if set, we use this query to detect latest public cloud tools image which used for running
            # all public cloud related tests in openQA
            if "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY" in settings:
                settings = apply_pc_tools_image(settings)
                if not settings.get("PUBLIC_CLOUD_TOOLS_IMAGE_BASE", False):
                    continue

            # parse Public-Cloud pint query if present
            if "PUBLIC_CLOUD_PINT_QUERY" in settings:
                settings = apply_publiccloud_pint_image(settings)
                if not settings.get("PUBLIC_CLOUD_IMAGE_ID", False):
                    continue

            self.set_obsoletion(settings)
            full_post["openqa"].update(settings)
            full_post["openqa"]["FLAVOR"] = self.flavor
            full_post["openqa"]["ARCH"] = arch

            for template, issues in test_incidents.items():
                full_post["openqa"][template] = ",".join(str(x) for x in issues)
                full_post["qem"]["incidents"] += issues
            for template, issues in test_repos.items():
                full_post["openqa"][template] = ",".join(issues)

            full_post["qem"]["incidents"] = [
                str(inc) for inc in set(full_post["qem"]["incidents"])
            ]
            if not full_post["qem"]["incidents"]:
                continue

            full_post["openqa"]["__DASHBOARD_INCIDENTS_URL"] = ",".join(
                f"{QEM_DASHBOARD}incident/{inc}"
                for inc in set(full_post["qem"]["incidents"])
            )
            full_post["openqa"]["__SMELT_INCIDENTS_URL"] = ",".join(
                f"https://smelt.suse.de/incident/{inc}"
                for inc in set(full_post["qem"]["incidents"])
            )

            full_post["qem"]["settings"] = full_post["openqa"]
            full_post["qem"]["repohash"] = full_post["openqa"]["REPOHASH"]
            full_post["qem"]["build"] = full_post["openqa"]["BUILD"]
            full_post["qem"]["arch"] = full_post["openqa"]["ARCH"]
            full_post["qem"]["product"] = self.product

            # add to ret
            ret.append(full_post)

        return ret
