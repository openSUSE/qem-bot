# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import datetime
from collections import defaultdict
from itertools import chain
from logging import getLogger
from typing import Any, NamedTuple

from openqabot import DEPRIORITIZE_LIMIT, DOWNLOAD_MAINTENANCE, QEM_DASHBOARD, SMELT_URL
from openqabot.dashboard import get_json
from openqabot.errors import NoTestIssuesError, SameBuildExistsError
from openqabot.loader.repohash import merge_repohash
from openqabot.pc_helper import apply_pc_tools_image, apply_publiccloud_pint_image
from openqabot.utc import UTC

from . import ProdVer, Repos
from .baseconf import BaseConf
from .incident import Incident

log = getLogger("bot.types.aggregate")


class _PostData(NamedTuple):
    test_incidents: defaultdict[list]
    test_repos: defaultdict[list]
    repohash: str
    build: str


class Aggregate(BaseConf):
    def __init__(
        self,
        product: str,
        product_repo: list[str] | str | None,
        product_version: str | None,
        settings: dict[str, Any],
        config: dict[str, Any],
    ) -> None:
        super().__init__(product, product_repo, product_version, settings, config)
        self.flavor = config["FLAVOR"]
        self.archs = config["archs"]
        self.onetime = config.get("onetime", False)
        self.test_issues = self.normalize_repos(config)

    @staticmethod
    def normalize_repos(config: dict[str, Any]) -> dict[str, ProdVer]:
        try:
            repos = {
                key: ProdVer(value.split(":")[0], value.split(":")[1]) for key, value in config["test_issues"].items()
            }
        except KeyError as e:
            raise NoTestIssuesError from e

        return repos

    def __repr__(self) -> str:
        return f"<Aggregate product: {self.product}>"

    @staticmethod
    def get_buildnr(repohash: str, old_repohash: str, build: str) -> str:
        today = datetime.datetime.now(tz=UTC).date().strftime("%Y%m%d")

        if build.startswith(today) and repohash == old_repohash:
            raise SameBuildExistsError

        counter = int(build.rsplit("-", maxsplit=1)[-1]) + 1 if build.startswith(today) else 1
        return f"{today}-{counter}"

    def _filter_incidents(self, incidents: list[Incident]) -> list[Incident]:
        valid_incidents = []
        for i in incidents:
            if not any((i.livepatch, i.staging)):
                if self.filter_embargoed(self.flavor) and i.embargoed:
                    log.debug(
                        "Incident %s is skipped because filtering embargoed is on and incident has embargoed True",
                        i.id,
                    )
                else:
                    valid_incidents.append(i)
        return valid_incidents

    def _get_test_incidents_and_repos(
        self, valid_incidents: list[Incident], issues_arch: str
    ) -> tuple[defaultdict[list], defaultdict[list]]:
        test_incidents = defaultdict(list)
        test_repos = defaultdict(list)

        for inc in valid_incidents:
            for issue, template in self.test_issues.items():
                if Repos(template.product, template.version, issues_arch) in inc.channels:
                    test_incidents[issue].append(inc)

        for issue, incs in test_incidents.items():
            tmpl = issue.replace("ISSUES", "REPOS")
            test_repos[tmpl].extend([
                f"{DOWNLOAD_MAINTENANCE}{inc}/SUSE_Updates_{self.test_issues[issue].product}_{self.test_issues[issue].version}/"
                if self.test_issues[issue].product.startswith("openSUSE")
                else f"{DOWNLOAD_MAINTENANCE}{inc}/SUSE_Updates_{self.test_issues[issue].product}_{self.test_issues[issue].version}_{issues_arch}/"
                for inc in incs
            ])
        return test_incidents, test_repos

    def _create_full_post(
        self,
        arch: str,
        data: _PostData,
        ci_url: str | None,
    ) -> dict[str, Any] | None:
        full_post: dict[str, Any] = {}
        full_post["openqa"] = {}
        full_post["qem"] = {}
        full_post["qem"]["incidents"] = []
        full_post["qem"]["settings"] = {}
        full_post["api"] = "api/update_settings"
        if ci_url:
            full_post["openqa"]["__CI_JOB_URL"] = ci_url

        full_post["openqa"]["REPOHASH"] = data.repohash
        full_post["openqa"]["BUILD"] = data.build

        settings = self.settings.copy()

        if "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY" in settings:
            settings = apply_pc_tools_image(settings)
            if not settings.get("PUBLIC_CLOUD_TOOLS_IMAGE_BASE", False):
                return None

        if "PUBLIC_CLOUD_PINT_QUERY" in settings:
            settings = apply_publiccloud_pint_image(settings)
            if not settings.get("PUBLIC_CLOUD_IMAGE_ID", False):
                return None

        full_post["openqa"].update(settings)
        full_post["openqa"]["FLAVOR"] = self.flavor
        full_post["openqa"]["ARCH"] = arch
        full_post["openqa"]["_DEPRIORITIZEBUILD"] = 1

        if DEPRIORITIZE_LIMIT is not None:
            full_post["openqa"]["_DEPRIORITIZE_LIMIT"] = DEPRIORITIZE_LIMIT

        for template, issues in data.test_incidents.items():
            full_post["openqa"][template] = ",".join(str(x) for x in issues)
            full_post["qem"]["incidents"] += issues
        for template, issues in data.test_repos.items():
            full_post["openqa"][template] = ",".join(issues)

        full_post["qem"]["incidents"] = [str(inc) for inc in set(full_post["qem"]["incidents"])]
        if not full_post["qem"]["incidents"]:
            return None

        full_post["openqa"]["__DASHBOARD_INCIDENTS_URL"] = ",".join(
            f"{QEM_DASHBOARD}incident/{inc}" for inc in full_post["qem"]["incidents"]
        )
        full_post["openqa"]["__SMELT_INCIDENTS_URL"] = ",".join(
            f"{SMELT_URL}/incident/{inc}" for inc in full_post["qem"]["incidents"]
        )

        full_post["qem"]["settings"] = full_post["openqa"]
        full_post["qem"]["repohash"] = full_post["openqa"]["REPOHASH"]
        full_post["qem"]["build"] = full_post["openqa"]["BUILD"]
        full_post["qem"]["arch"] = full_post["openqa"]["ARCH"]
        full_post["qem"]["product"] = self.product

        return full_post

    def __call__(
        self,
        incidents: list[Incident],
        token: dict[str, str],
        ci_url: str | None,
        *,
        ignore_onetime: bool = False,
    ) -> list[dict[str, Any]]:
        ret = []

        for arch in self.archs:
            # Temporary workaround for applying the correct architecture on jobs, which use a helper VM
            issues_arch = self.settings.get("TEST_ISSUES_ARCH", arch)

            valid_incidents = self._filter_incidents(incidents)
            test_incidents, test_repos = self._get_test_incidents_and_repos(valid_incidents, issues_arch)

            repohash = merge_repohash(
                sorted({str(inc) for inc in chain.from_iterable(test_incidents.values())}),
            )

            try:
                old_jobs = get_json(
                    "api/update_settings",
                    params={"product": self.product, "arch": arch},
                    headers=token,
                )
            except Exception:
                log.exception("")
                old_jobs = None

            old_repohash = old_jobs[0].get("repohash", "") if old_jobs else ""
            old_build = old_jobs[0].get("build", "") if old_jobs else ""

            try:
                build = self.get_buildnr(
                    repohash,
                    old_repohash,
                    old_build,
                )
            except SameBuildExistsError:
                log.info(
                    "For %s aggreagate on %s there is existing build",
                    self.product,
                    arch,
                )
                continue

            if not ignore_onetime and (self.onetime and build.split("-")[-1] != "1"):
                continue

            full_post = self._create_full_post(
                arch,
                _PostData(test_incidents, test_repos, repohash, build),
                ci_url,
            )

            if full_post:
                ret.append(full_post)

        return ret
