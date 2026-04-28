# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Trigger testing for PR(s) with certain label."""

from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import Any

import requests
from openqa_client.exceptions import RequestError
from osc import conf

from openqabot import config
from openqabot.loader.crawler import Crawler
from openqabot.loader.triggerconfig import TriggerConfig
from openqabot.types.isomatch import IsoMatch
from openqabot.types.pullrequest import PullRequest
from openqabot.types.types import Data
from openqabot.utils import get_configs_from_path

from .commenter import Commenter
from .loader.gitea import (
    approve_pr,
    generate_repo_url,
    get_gitea_staging_config,
    get_open_prs,
    make_token_header,
)
from .openqa import OpenQAInterface

log = getLogger("bot.giteatrigger")

ISO_REGEX = (
    r"(?P<product>SLES)-(?P<version>[\d\.]+)-Online-"
    r"(?P<arch>x86_64)-Build(?P<build>[0-9\.]+)\.install.iso$"
)


class GiteaTrigger:
    """Trigger testing for PR(s) with certain label."""

    def __init__(self, args: Namespace) -> None:
        """Initialize GiteaTrigger class.

        Args:
            args (Namespace): command line arguments needed for initialization

        """
        self.dry: bool = args.dry
        self.gitea_token: dict[str, str] = make_token_header(args.gitea_token)
        self.config_list: list[TriggerConfig] = get_configs_from_path(
            args.trigger_config, "trigger_config", TriggerConfig.from_config_entry
        )
        self.gitea_project: Any = args.gitea_project
        self.pr_number: int = args.pr_number
        self.openqa: OpenQAInterface = OpenQAInterface()
        self.pr_required_labels: set[str] = set(args.pr_label.split(","))
        staging_config: Any = get_gitea_staging_config(self.gitea_token)
        self.staging_config_project = staging_config["StagingProject"].replace(":", ":/")
        self.staging_config_qa_labels: dict[str, str] = {
            item["Label"]: item["Name"] for item in staging_config.get("QA", [])
        }
        self.prs: list[PullRequest] = []
        self.comment: bool = getattr(args, "comment", False)
        self.commenter: Commenter = Commenter(args, submissions=[])
        conf.get_config(override_apiurl=config.settings.obs_url)

    def is_openqa_triggering_needed(self, matched_iso: IsoMatch, trigger_config: TriggerConfig) -> bool:
        """Check if certain build was already triggered in openQA.

        Args:
            matched_iso (IsoMatch): The matched ISO information.
            trigger_config (TriggerConfig): The triggering configuration.

        Returns:
            bool: True if tests suppose to be triggered so they haven't triggered yet
                  False if tests already triggered so new trigger is not needed

        """
        openqa_settings = {
            "version": matched_iso.version,
            "flavor": trigger_config.flavor,
            "arch": matched_iso.arch,
            "distri": trigger_config.distri,
            "build": matched_iso.build,
        }
        return not self.openqa.get_scheduled_product_stats(openqa_settings)

    def check_pullrequest(self, pullrequest: PullRequest, trigger_config: TriggerConfig) -> None:
        """Evaluate a pull request and triggers openQA tests if new artifacts are available.

        The method constructs the repository URL, extracts the build version from
        the available ISO artifacts using regex, and checks if this specific
        build has already been tested. If testing is required, it posts a new
        job to openQA with the relevant configuration.

        Args:
            pullrequest (PullRequest): The pull request object to validate and test.
            trigger_config (TriggerConfig): The triggering configuration.

        """
        log.info("Evaluating PR %s for openQA triggering with config: %s", pullrequest.number, trigger_config)
        repo_url = generate_repo_url(pullrequest, self.staging_config_qa_labels, self.staging_config_project)
        matched_iso_regex = Crawler(verify=True).get_regex_match_from_url(repo_url, ISO_REGEX)

        if not matched_iso_regex:
            log.warning("No ISO found for %s in %s", pullrequest, repo_url)
            return

        matched_iso = IsoMatch(matched_iso_regex, pullrequest.number)

        if self.is_openqa_triggering_needed(matched_iso, trigger_config):
            openqa_settings = {
                "ISO_URL": f"{repo_url}/{matched_iso_regex.group(0)}",
                "_GITEA_PR": str(pullrequest.number),
                "VERSION": matched_iso.version,
                "FLAVOR": trigger_config.flavor,
                "ARCH": matched_iso.arch,
                "DISTRI": trigger_config.distri,
                "BUILD": matched_iso.build,
            }
            self.openqa.post_job(openqa_settings)
            log.info("Triggered openQA tests for PR %s on %s", pullrequest.number, matched_iso.arch)
        else:
            log.info("openQA tests for PR %s (build %s) are already covered", pullrequest.number, matched_iso.build)
            if self.comment:
                self.comment_on_pr(pullrequest, matched_iso, trigger_config)

    def comment_on_pr(self, pullrequest: PullRequest, matched_iso: IsoMatch, trigger_config: TriggerConfig) -> None:
        """Comment on PR if openQA results are available."""
        data = Data(
            pullrequest.number,
            "git",
            0,
            trigger_config.flavor,
            matched_iso.arch,
            trigger_config.distri,
            matched_iso.version,
            matched_iso.build,
            matched_iso.product,
        )

        try:
            jobs = self.openqa.get_jobs(data)
            for j in jobs:
                j.setdefault("build", matched_iso.build)
        except (requests.exceptions.RequestException, RequestError):
            log.exception("Failed to fetch jobs for PR %s", pullrequest.number)
            return

        if res := self.commenter.generate_comment(pullrequest, jobs):
            self.commenter.gitea_comment(pullrequest, *res)
            if res[1] == "passed":
                if self.dry:
                    log.info("Dry run: Would approve PR %s", pullrequest.number)
                else:
                    msg = (
                        f"Request accepted for '{config.settings.obs_group}' "
                        f"based on data in {config.settings.dashboard_url()}"
                    )
                    approve_pr(self.gitea_token, pullrequest.project, pullrequest.number, pullrequest.commit_sha, msg)

    def get_prs_by_label(self) -> None:
        """Get all open PRs and filter them by defined label."""
        open_prs: list[PullRequest] = get_open_prs(
            self.gitea_token,
            self.gitea_project,
            number=self.pr_number,
        )
        log.info(
            "Loaded %d active PRs from %s",
            len(open_prs),
            self.gitea_project,
        )
        for pr in open_prs:
            # we're looking only for PRs which has ALL labels defined via '--pr-label' parameter AND
            # at least one for labels defined in staging.config
            qa_labels = set(self.staging_config_qa_labels.keys())
            if pr.has_all_labels(self.pr_required_labels) and pr.has_any_label(qa_labels):
                self.prs.append(pr)
            else:
                log.debug("PR %s disregarded (labels: %s)", pr.number, pr.labels)
        log.debug(
            "Data for %d pullrequest: %s",
            len(self.prs),
            pformat(self.prs),
        )

    def __call__(self) -> int:
        """Run test triggering logic.

        Returns:
            int: 0 if all went well

        """
        self.get_prs_by_label()

        for trigger_config in self.config_list:
            for pr in self.prs:
                self.check_pullrequest(pr, trigger_config)

        return 0
