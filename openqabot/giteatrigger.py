# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Trigger testing for PR(s) with certain label."""

from argparse import Namespace
from logging import getLogger
from pprint import pformat
from typing import Any

from osc import conf

from openqabot import config
from openqabot.loader.crawler import Crawler
from openqabot.types.pullrequest import PullRequest

from .loader.gitea import (
    generate_repo_url,
    get_open_prs,
    make_token_header,
)
from .openqa import OpenQAInterface

log = getLogger("bot.giteatrigger")

ISO_REGEX = r"(?P<product>SLES)-(?P<version>[\d\.]+)-Online-(?P<arch>x86_64)-Build(?P<build>[0-9\.]+)\.install.iso$"


class GiteaTrigger:
    """Trigger testing for PR(s) with certain label."""

    def __init__(self, args: Namespace) -> None:
        """Initialize GiteaTrigger class.

        Args:
            args (Namespace): command line arguments needed for initialization

        """
        self.dry: bool = args.dry
        self.gitea_token: dict[str, str] = make_token_header(args.gitea_token)
        self.gitea_repo: Any = args.gitea_repo
        self.pr_number: int = args.pr_number
        self.openqa: OpenQAInterface = OpenQAInterface()
        self.pr_required_labels: set[str] = set(args.pr_label.split(","))
        self.flavor: str = "Online-Staging"
        self.distri: str = "sle"
        self.prs: list[PullRequest] = []
        conf.get_config(override_apiurl=config.settings.obs_url)

    def is_openqa_triggering_needed(self, version: str, arch: str, build: str) -> bool:
        """Check if certain build was already triggered in openQA.

        Args:
            version (str): version for which tests suppose to be triggered
            arch (str): arch for which tests suppose to be triggered
            build (str): build for which tests suppose to be triggered

        Returns:
            bool: True if tests suppose to be triggered so they haven't triggered yet
                  False if tests already triggered so new trigger is not needed

        """
        openqa_settings = {
            "version": version,
            "flavor": self.flavor,
            "arch": arch,
            "distri": self.distri,
            "build": build,
        }
        previous_trigger = self.openqa.get_scheduled_product_stats(openqa_settings)
        return len(previous_trigger.keys()) == 0

    def check_pullrequest(self, pullrequest: PullRequest) -> None:
        """Evaluate a pull request and triggers openQA tests if new artifacts are available.

        The method constructs the repository URL, extracts the build version from
        the available ISO artifacts using regex, and checks if this specific
        build has already been tested. If testing is required, it posts a new
        job to openQA with the relevant configuration.

        Args:
            pullrequest (PullRequest): The pull request object to validate and test.

        """
        log.info("Triggering tests for PR %s", pullrequest.number)
        repo_url = generate_repo_url(pullrequest, self.gitea_token)
        matched_iso = Crawler(verify=True).get_regex_match_from_url(repo_url, ISO_REGEX)

        if matched_iso:
            product = matched_iso.group("product")
            version = matched_iso.group("version")
            arch = matched_iso.group("arch")
            build_num = matched_iso.group("build")
            build = f"PR-{pullrequest.number}-{build_num}:{product}-{version}"
            if self.is_openqa_triggering_needed(version, arch, build):
                openqa_settings = {
                    "ISO_URL": f"{repo_url}/{matched_iso.group(0)}",
                    "_GITEA_PR": str(pullrequest.number),
                    "VERSION": version,
                    "FLAVOR": self.flavor,
                    "ARCH": arch,
                    "DISTRI": self.distri,
                    "BUILD": build,
                }
                self.openqa.post_job(openqa_settings)
                log.info("Triggered openQA job for PR %s on %s", pullrequest.number, arch)
            else:
                log.debug("Build %s already covered", build)
        else:
            log.warning("No ISO found for %s in %s", pullrequest, repo_url)

    def get_prs_by_label(self) -> None:
        """Get all open PRs and filter them by defined label."""
        open_prs: list[Any] = get_open_prs(
            self.gitea_token,
            self.gitea_repo,
            fake_data=False,
            number=self.pr_number,
        )
        log.info(
            "Loaded %d active PRs from %s",
            len(open_prs),
            self.gitea_repo,
        )
        for pr in open_prs:
            pr_id = pr.get("number", "?")
            log.debug("Fetching info for PR git:%s from Gitea", pr_id)
            try:
                pullrequest = PullRequest(
                    number=pr["number"],
                    raw_labels=pr["labels"],
                    repo_name=pr["base"]["repo"]["name"],
                    branch=pr["base"]["label"],
                )
                if pullrequest.has_labels(self.pr_required_labels):
                    self.prs.append(pullrequest)
            except Exception:
                log.exception("Unable to process PR git:%s", pr_id)
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

        for pr in self.prs:
            self.check_pullrequest(pr)

        return 0
