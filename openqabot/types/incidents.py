# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from logging import getLogger
from typing import Any, NamedTuple

import requests

from openqabot.config import (
    DOWNLOAD_BASE,
    DOWNLOAD_MAINTENANCE,
    GITEA,
    OBSOLETE_PARAMS,
    QEM_DASHBOARD,
    SMELT_URL,
)
from openqabot.errors import NoRepoFoundError
from openqabot.loader import gitea
from openqabot.pc_helper import apply_pc_tools_image, apply_publiccloud_pint_image
from openqabot.utils import retry3 as retried_requests

from . import ProdVer, Repos
from .baseconf import BaseConf
from .incident import Incident


class IncContext(NamedTuple):
    inc: Incident
    arch: str
    flavor: str
    data: dict[str, Any]


class IncConfig(NamedTuple):
    token: dict[str, str]
    ci_url: str | None
    ignore_onetime: bool


log = getLogger("bot.types.incidents")

BASE_PRIO = 50


class Incidents(BaseConf):
    def __init__(  # noqa: PLR0917 too-many-positional-arguments
        self,
        product: str,
        product_repo: list[str] | str | None,
        product_version: str | None,
        settings: dict[str, Any],
        config: dict[str, Any],
        extrasettings: set[str],
    ) -> None:
        super().__init__(product, product_repo, product_version, settings, config)
        self.flavors = self.normalize_repos(config["FLAVOR"])
        self.singlearch = extrasettings

    def __repr__(self) -> str:
        return f"<Incidents product: {self.product}>"

    @staticmethod
    def product_version_from_issue_channel(issue: str) -> ProdVer:
        channel_parts = issue.split(":")
        version_parts = channel_parts[1].split("#")
        return ProdVer(channel_parts[0], *version_parts)

    @staticmethod
    def normalize_repos(config: dict[str, Any]) -> dict[str, Any]:
        return {
            flavor: {
                key: (
                    {
                        template: Incidents.product_version_from_issue_channel(channel)
                        for template, channel in value.items()
                    }
                    if key == "issues"
                    else value
                )
                for key, value in data.items()
            }
            for flavor, data in config.items()
        }

    @staticmethod
    def _repo_osuse(chan: Repos) -> tuple[str, str, str] | tuple[str, str]:
        if chan.product == "openSUSE-SLE":
            return chan.product, chan.version
        return chan.product, chan.version, chan.arch

    @staticmethod
    def _is_scheduled_job(token: dict[str, str], inc: Incident, arch: str, ver: str, flavor: str) -> bool:
        jobs = {}
        try:
            url = f"{QEM_DASHBOARD}api/incident_settings/{inc.id}"
            jobs = retried_requests.get(url, headers=token).json()
        except (requests.exceptions.RequestException, json.JSONDecodeError):
            log.exception("Dashboard API error: Could not retrieve scheduled jobs for incident %s", inc.id)

        if not jobs:
            return False

        if isinstance(jobs, dict) and "error" in jobs:
            return False

        revs = inc.revisions_with_fallback(arch, ver)
        if not revs:
            return False
        return any(
            job["flavor"] == flavor
            and job["arch"] == arch
            and job["version"] == ver
            and job["settings"]["REPOHASH"] == revs
            for job in jobs
        )

    def _make_repo_url(self, inc: Incident, chan: Repos) -> str:
        return (
            gitea.compute_repo_url_for_job_setting(DOWNLOAD_BASE, chan, self.product_repo, self.product_version)
            if chan.product == "SUSE:SLFO"
            else f"{DOWNLOAD_MAINTENANCE}{inc.id}/SUSE_Updates_{'_'.join(self._repo_osuse(chan))}"
        )

    def _handle_incident(  # noqa: PLR0911,C901
        self, ctx: IncContext, cfg: IncConfig
    ) -> dict[str, Any] | None:
        inc = ctx.inc
        arch = ctx.arch
        flavor = ctx.flavor
        data = ctx.data
        if inc.type == "git" and not inc.ongoing:
            log.debug(
                "PR %s skipped (arch %s, flavor %s): PR is closed, approved, or review no longer requested",
                inc.id,
                arch,
                flavor,
            )
            return None
        if self.filter_embargoed(flavor) and inc.embargoed:
            log.info("Incident %s skipped: Embargoed and embargo-filtering enabled", inc.id)
            return None
        full_post: dict[str, Any] = {}
        full_post["api"] = "api/incident_settings"
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
        full_post["openqa"].update(OBSOLETE_PARAMS)
        full_post["openqa"]["INCIDENT_ID"] = inc.id

        if cfg.ci_url:
            full_post["openqa"]["__CI_JOB_URL"] = cfg.ci_url
        if inc.staging:
            return None

        if "packages" in data and data["packages"] is not None and not inc.contains_package(data["packages"]):
            return None

        if (
            "excluded_packages" in data
            and data["excluded_packages"] is not None
            and inc.contains_package(data["excluded_packages"])
        ):
            return None

        if inc.livepatch:
            full_post["openqa"]["KGRAFT"] = "1"

        full_post["openqa"]["BUILD"] = f":{inc.id}:{inc.packages[0]}"

        if inc.rrid:
            full_post["openqa"]["RRID"] = inc.rrid

        # old bot used variable "REPO_ID"
        inc.compute_revisions_for_product_repo(self.product_repo, self.product_version)
        revs = inc.revisions_with_fallback(arch, self.settings["VERSION"])
        if not revs:
            return None
        full_post["openqa"]["REPOHASH"] = revs
        channels_set = set()
        issue_dict = {}

        log.debug("Incident %s: Active channels: %s", inc.id, inc.channels)
        for issue, channel in data["issues"].items():
            log.debug(
                "Checking metadata channel: product=%s, version=%s, arch=%s",
                channel.product,
                f"{channel.version}#{channel.product_version}",
                arch,
            )
            f_channel = Repos(channel.product, channel.version, arch, channel.product_version)
            if channel.product == "SLFO":
                for inc_channel in inc.channels:
                    if (
                        inc_channel.product == "SUSE:SLFO"
                        and (
                            channel.product_version == inc_channel.product_version
                            if len(channel.product_version) > 0
                            else inc_channel.version.startswith(channel.version)
                        )
                        and channel.product_version in {"", inc_channel.product_version}
                        and inc_channel.arch == arch
                    ):
                        issue_dict[issue] = inc
                        channels_set.add(inc_channel)
            elif f_channel in inc.channels:
                issue_dict[issue] = inc
                channels_set.add(f_channel)

        if not issue_dict:
            log.debug("Incident %s skipped for %s on %s: No matching channels found in metadata", inc.id, flavor, arch)
            return None

        if "required_issues" in data and set(issue_dict.keys()).isdisjoint(data["required_issues"]):
            return None

        version = self.settings["VERSION"]
        if not cfg.ignore_onetime and self._is_scheduled_job(cfg.token, inc, arch, version, flavor):
            log.info("Incident %s already scheduled for %s on %s (version: %s)", inc.id, flavor, arch, version)
            return None

        if (
            "Kernel" in flavor
            and not inc.livepatch
            and not flavor.endswith("Azure")
            and set(issue_dict.keys()).isdisjoint({
                "OS_TEST_ISSUES",  # standard product dir
                "LTSS_TEST_ISSUES",  # LTSS product dir
                "BASE_TEST_ISSUES",  # GA product dir SLE15+
                "RT_TEST_ISSUES",  # realtime kernel
                "COCO_TEST_ISSUES",  # Confidential Computing kernel
            })
        ):
            log.warning("Incident %s skipped: Kernel incident missing product repository", inc.id)
            return None

        for key, value in issue_dict.items():
            full_post["openqa"][key] = str(value.id)

        full_post["openqa"]["INCIDENT_REPO"] = ",".join(
            sorted(self._make_repo_url(inc, chan) for chan in channels_set),
        )  # sorted for testability

        full_post["qem"]["withAggregate"] = True
        aggregate_job = data.get("aggregate_job", True)

        # some arch specific packages doesn't have aggregate tests
        if not self.singlearch.isdisjoint(set(inc.packages)):
            full_post["qem"]["withAggregate"] = False

        def _should_aggregate(data: dict[str, Any], openqa_keys: set[str]) -> bool:
            pos = set(data.get("aggregate_check_true", []))
            neg = set(data.get("aggregate_check_false", []))

            if pos and not pos.isdisjoint(openqa_keys):
                return False
            if neg and neg.isdisjoint(openqa_keys):
                return False
            return bool(neg and pos)

        if not aggregate_job and not _should_aggregate(data, set(full_post["openqa"].keys())):
            full_post["qem"]["withAggregate"] = False
            log.info("Incident %s: Aggregate job not required", inc.id)

        delta_prio = data.get("override_priority", 0)

        if delta_prio:
            delta_prio -= 50
        else:
            if flavor.endswith("Minimal"):
                delta_prio += 5
            else:
                delta_prio += 10
            if inc.emu:
                delta_prio = -20

        # override default prio only for specific jobs
        if delta_prio:
            full_post["openqa"]["_PRIORITY"] = BASE_PRIO + delta_prio

        # add custom vars to job settings
        if "params_expand" in data and any(
            forbidden_key in data["params_expand"] for forbidden_key in ["DISTRI", "VERSION"]
        ):
            log.error(
                "Flavor %s ignored: 'params_expand' contains forbidden keys 'DISTRI' or 'VERSION'",
                flavor,
            )
            return None

        if "params_expand" in data:
            full_post["openqa"].update(data["params_expand"])

        url = (
            f"{GITEA}/products/{inc.project}/pulls/{inc.id}"
            if inc.project == "SLFO"
            else f"{SMELT_URL}/incident/{inc.id}"
        )
        dashboard_url = f"{QEM_DASHBOARD}incident/{inc.id}"
        full_post["openqa"]["__SOURCE_CHANGE_URL"] = url
        full_post["openqa"]["__DASHBOARD_INCIDENT_URL"] = dashboard_url

        settings = full_post["openqa"].copy()

        # if set, we use this query to detect latest public cloud tools image which used for running
        # all public cloud related tests in openQA
        if "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY" in settings:
            settings = apply_pc_tools_image(settings)
            if not settings.get("PUBLIC_CLOUD_TOOLS_IMAGE_BASE", False):
                return None

        # parse Public-Cloud pint query if present
        if "PUBLIC_CLOUD_PINT_QUERY" in settings:
            settings = apply_publiccloud_pint_image(settings)
            if not settings.get("PUBLIC_CLOUD_IMAGE_ID", False):
                return None

        full_post["openqa"] = settings
        full_post["qem"]["settings"] = settings
        return full_post

    def _process_inc_context(self, ctx: IncContext, cfg: IncConfig) -> dict[str, Any] | None:
        ctx.inc.arch_filter = ctx.data["archs"]
        try:
            return self._handle_incident(ctx, cfg)
        except NoRepoFoundError as e:
            log.info(
                "Incident %s skipped: RepoHash calculation failed for project %s: %s",
                ctx.inc.id,
                ctx.inc.project,
                e,
            )
            return None

    def __call__(
        self,
        incidents: list[Incident],
        token: dict[str, str],
        ci_url: str | None,
        *,
        ignore_onetime: bool,
    ) -> list[dict[str, Any]]:
        cfg = IncConfig(token=token, ci_url=ci_url, ignore_onetime=ignore_onetime)
        results = [
            self._process_inc_context(
                IncContext(
                    inc=inc,
                    arch=arch,
                    flavor=flavor,
                    data=data,
                ),
                cfg,
            )
            for flavor, data in self.flavors.items()
            for arch in data["archs"]
            for inc in incidents
        ]
        return [r for r in results if r]
