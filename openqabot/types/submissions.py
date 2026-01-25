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
from openqabot.loader import gitea
from openqabot.pc_helper import apply_pc_tools_image, apply_publiccloud_pint_image
from openqabot.utils import retry3 as retried_requests

from .baseconf import BaseConf, JobConfig
from .submission import Submission
from .types import ProdVer, Repos


class SubContext(NamedTuple):
    sub: Submission
    arch: str
    flavor: str
    data: dict[str, Any]


class SubConfig(NamedTuple):
    token: dict[str, str]
    ci_url: str | None
    ignore_onetime: bool


log = getLogger("bot.types.submissions")

BASE_PRIO = 50


class Submissions(BaseConf):
    def __init__(self, config: JobConfig, extrasettings: set[str]) -> None:
        super().__init__(config)
        self.flavors = self.normalize_repos(config.config["FLAVOR"])
        self.singlearch = extrasettings
        self.valid_archs = {arch for data in self.flavors.values() for arch in data["archs"]}

    def __repr__(self) -> str:
        return f"<Submissions product: {self.product}>"

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
                        template: Submissions.product_version_from_issue_channel(channel)
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
    def repo_osuse(chan: Repos) -> tuple[str, str, str] | tuple[str, str]:
        if chan.product == "openSUSE-SLE":
            return chan.product, chan.version
        return chan.product, chan.version, chan.arch

    @staticmethod
    def is_scheduled_job(token: dict[str, str], ctx: SubContext, ver: str, submission_type: str | None = None) -> bool:
        jobs = {}
        try:
            url = f"{QEM_DASHBOARD}api/incident_settings/{ctx.sub.id}"
            params = {}
            if submission_type:
                params["type"] = submission_type
            jobs = retried_requests.get(url, headers=token, params=params).json()
        except (requests.exceptions.RequestException, json.JSONDecodeError):
            log.exception("Dashboard API error: Could not retrieve scheduled jobs for submission %s", ctx.sub)

        if not jobs:
            return False

        if isinstance(jobs, dict) and "error" in jobs:
            return False

        revs = ctx.sub.revisions_with_fallback(ctx.arch, ver)
        if not revs:
            return False
        return any(
            job["flavor"] == ctx.flavor
            and job["arch"] == ctx.arch
            and job["version"] == ver
            and job["settings"]["REPOHASH"] == revs
            for job in jobs
        )

    def make_repo_url(self, sub: Submission, chan: Repos) -> str:
        return (
            gitea.compute_repo_url_for_job_setting(DOWNLOAD_BASE, chan, self.product_repo, self.product_version)
            if chan.product == "SUSE:SLFO"
            else f"{DOWNLOAD_MAINTENANCE}{sub.id}/SUSE_Updates_{'_'.join(self.repo_osuse(chan))}"
        )

    def get_matching_channels(self, sub: Submission, channel: ProdVer, arch: str) -> list[Repos]:
        if channel.product == "SLFO":
            return [
                ic
                for ic in sub.channels
                if ic.arch == arch
                and (
                    channel.product_version == ic.product_version
                    if channel.product_version
                    else ic.version.startswith(channel.version)
                )
            ]
        f_channel = Repos(channel.product, channel.version, arch, channel.product_version)
        return [f_channel] if f_channel in sub.channels else []

    def should_skip(self, ctx: SubContext, cfg: SubConfig, matches: dict[str, list[Repos]]) -> bool:
        sub, arch, flavor, data = ctx.sub, ctx.arch, ctx.flavor, ctx.data
        if not sub.ongoing:
            log.debug("Submission %s skipped (%s, %s): closed/approved/review no longer requested", sub, arch, flavor)
            return True
        if (self.filter_embargoed(flavor) and sub.embargoed) or sub.staging:
            if sub.embargoed:
                log.info("Submission %s skipped: Embargoed and embargo-filtering enabled", sub)
            return True

        # Check packages and channels
        pkg_mismatch = (data.get("packages") is not None and not sub.contains_package(data["packages"])) or (
            data.get("excluded_packages") is not None and sub.contains_package(data["excluded_packages"])
        )
        if (
            pkg_mismatch
            or not matches
            or ("required_issues" in data and set(matches).isdisjoint(data["required_issues"]))
        ):
            if not matches:
                log.debug(
                    "Submission %s skipped for %s on %s: No matching channels found in metadata", sub, flavor, arch
                )
            return True

        if not cfg.ignore_onetime and self.is_scheduled_job(
            cfg.token, ctx, self.settings["VERSION"], submission_type=sub.type
        ):
            log.info("Submission %s already scheduled for %s on %s", sub, flavor, arch)
            return True

        if "Kernel" in flavor and not sub.livepatch and not flavor.endswith("Azure"):
            allowed = {"OS_TEST_ISSUES", "LTSS_TEST_ISSUES", "BASE_TEST_ISSUES", "RT_TEST_ISSUES", "COCO_TEST_ISSUES"}
            if set(matches).isdisjoint(allowed):
                log.warning("Submission %s skipped: Kernel submission missing product repository", sub)
                return True

        return False

    def get_base_settings(self, ctx: SubContext, revs: int, cfg: SubConfig) -> dict[str, Any]:
        sub, arch, flavor = ctx.sub, ctx.arch, ctx.flavor
        return {
            **self.settings,
            "ARCH": arch,
            "FLAVOR": flavor,
            "VERSION": self.settings["VERSION"],
            "DISTRI": self.settings["DISTRI"],
            "INCIDENT_ID": sub.id,
            "REPOHASH": revs,
            "BUILD": f":{sub.type}:{sub.id}:{sub.packages[0]}",
            **OBSOLETE_PARAMS,
            **({"__CI_JOB_URL": cfg.ci_url} if cfg.ci_url else {}),
            **({"KGRAFT": "1"} if sub.livepatch else {}),
            **({"RRID": sub.rrid} if sub.rrid else {}),
        }

    def get_priority(self, ctx: SubContext) -> int | None:
        sub, flavor, data = ctx.sub, ctx.flavor, ctx.data
        if delta_prio := data.get("override_priority", 0):
            delta_prio -= 50
        else:
            delta_prio = 5 if flavor.endswith("Minimal") else 10
            if sub.emu:
                delta_prio = -20
        return BASE_PRIO + delta_prio if delta_prio else None

    def apply_params_expand(self, settings: dict[str, Any], data: dict[str, Any], flavor: str) -> bool:
        if "params_expand" not in data:
            return True
        params = data["params_expand"]
        if any(k in params for k in ["DISTRI", "VERSION"]):
            log.error("Flavor %s ignored: 'params_expand' contains forbidden keys 'DISTRI' or 'VERSION'", flavor)
            return False
        settings.update(params)
        return True

    def add_metadata_urls(self, settings: dict[str, Any], sub: Submission) -> None:
        url = (
            f"{GITEA}/products/{sub.project}/pulls/{sub.id}"
            if sub.project == "SLFO"
            else f"{SMELT_URL}/incident/{sub.id}"
        )
        settings["__SOURCE_CHANGE_URL"] = url
        settings["__DASHBOARD_INCIDENT_URL"] = f"{QEM_DASHBOARD}incident/{sub.id}"

    def apply_pc_images(self, settings: dict[str, Any]) -> dict[str, Any] | None:
        if "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY" in settings:
            settings = apply_pc_tools_image(settings)
            if not settings.get("PUBLIC_CLOUD_TOOLS_IMAGE_BASE"):
                return None
        if "PUBLIC_CLOUD_PINT_QUERY" in settings:
            settings = apply_publiccloud_pint_image(settings)
            if not settings.get("PUBLIC_CLOUD_IMAGE_ID"):
                return None
        return settings

    def is_aggregate_needed(self, ctx: SubContext, openqa_keys: set[str]) -> bool:
        sub, data = ctx.sub, ctx.data
        if not self.singlearch.isdisjoint(set(sub.packages)):
            return False
        if data.get("aggregate_job", True):
            return True
        pos, neg = set(data.get("aggregate_check_true", [])), set(data.get("aggregate_check_false", []))
        if (pos and not pos.isdisjoint(openqa_keys)) or (neg and neg.isdisjoint(openqa_keys)):
            log.info("Submission %s: Aggregate job not required", sub)
            return False
        return bool(neg and pos)

    def handle_submission(self, ctx: SubContext, cfg: SubConfig) -> dict[str, Any] | None:
        sub, arch, flavor, data = ctx.sub, ctx.arch, ctx.flavor, ctx.data
        matches = {
            issue: matched
            for issue, channel in data.get("issues", {}).items()
            if (matched := self.get_matching_channels(sub, channel, arch))
        }
        if self.should_skip(ctx, cfg, matches):
            return None
        version = self.product_version or self.settings["VERSION"]
        if not sub.compute_revisions_for_product_repo(
            self.product_repo, self.product_version, limit_archs=self.valid_archs
        ):
            return None
        if not (revs := sub.revisions_with_fallback(arch, version)):
            return None
        settings = self.get_base_settings(ctx, revs, cfg)
        for issue in matches:
            settings[issue] = str(sub.id)
        all_repos = {c for matched in matches.values() for c in matched}
        repos = {c for c in all_repos if c.product_version == version} or all_repos
        settings["INCIDENT_REPO"] = ",".join(sorted(self.make_repo_url(sub, chan) for chan in repos))
        if prio := self.get_priority(ctx):
            settings["_PRIORITY"] = prio
        if not self.apply_params_expand(settings, data, flavor):
            return None
        self.add_metadata_urls(settings, sub)
        if not (settings := self.apply_pc_images(settings)):
            return None
        return {
            "api": "api/incident_settings",
            "qem": {
                "incident": sub.id,
                "type": sub.type,
                "arch": arch,
                "flavor": flavor,
                "version": self.settings["VERSION"],
                "withAggregate": self.is_aggregate_needed(ctx, set(settings.keys())),
                "settings": settings,
            },
            "openqa": settings,
        }

    def process_sub_context(self, ctx: SubContext, cfg: SubConfig) -> dict[str, Any] | None:
        return self.handle_submission(ctx, cfg)

    def __call__(
        self,
        submissions: list[Submission],
        token: dict[str, str],
        ci_url: str | None,
        *,
        ignore_onetime: bool,
    ) -> list[dict[str, Any]]:
        cfg = SubConfig(token=token, ci_url=ci_url, ignore_onetime=ignore_onetime)

        active = [
            s for s in submissions if s.compute_revisions_for_product_repo(self.product_repo, self.product_version)
        ]

        return [
            r
            for flavor, data in self.flavors.items()
            for arch in data["archs"]
            for sub in active
            if (r := self.process_sub_context(SubContext(sub, arch, flavor, data), cfg))
        ]
