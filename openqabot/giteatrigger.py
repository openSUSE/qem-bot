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
from openqabot.types.pullrequest import PullRequest
from openqabot.types.types import Data

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
        self.gitea_repo: Any = args.gitea_repo
        self.pr_number: int = args.pr_number
        self.openqa: OpenQAInterface = OpenQAInterface()
        self.pr_required_labels: set[str] = set(args.pr_label.split(","))
        staging_config: Any = get_gitea_staging_config(self.gitea_token)
        self.gitea_project = staging_config["StagingProject"].replace(":", ":/")
        self.staging_config_qa_labels: dict[str, str] = {
            item["Label"]: item["Name"] for item in staging_config.get("QA", [])
        }
        self.flavor: str = "Online-Staging"
        self.distri: str = "sle"
        self.prs: list[PullRequest] = []
        self.comment: bool = getattr(args, "comment", False)
        self.commenter: Commenter = Commenter(args, submissions=[])
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
        return not self.openqa.get_scheduled_product_stats(openqa_settings)

    def check_pullrequest(self, pullrequest: PullRequest) -> None:
        """Evaluate a pull request and triggers openQA tests if new artifacts are available.

        The method constructs the repository URL, extracts the build version from
        the available ISO artifacts using regex, and checks if this specific
        build has already been tested. If testing is required, it posts a new
        job to openQA with the relevant configuration.

        Args:
            pullrequest (PullRequest): The pull request object to validate and test.

        """
        log.info("Evaluating PR %s for openQA triggering", pullrequest.number)
        repo_url = generate_repo_url(pullrequest, self.staging_config_qa_labels, self.gitea_project)
        matched_iso = Crawler(verify=True).get_regex_match_from_url(repo_url, ISO_REGEX)

        if not matched_iso:
            log.warning("No ISO found for %s in %s", pullrequest, repo_url)
            return

        product, version, arch, build_num = (matched_iso.group(k) for k in ("product", "version", "arch", "build"))
        unique_version = f"{version}:PR-{pullrequest.number}"
        build = f"PR-{pullrequest.number}-{build_num}:{product}-{version}"

        if self.is_openqa_triggering_needed(unique_version, arch, build):
            openqa_settings = {
                "ISO_URL": f"{repo_url}/{matched_iso.group(0)}",
                "_GITEA_PR": str(pullrequest.number),
                "VERSION": unique_version,
                "FLAVOR": self.flavor,
                "ARCH": arch,
                "DISTRI": self.distri,
                "BUILD": build,
            }
            self.openqa.post_job(openqa_settings)
            log.info("Triggered openQA tests for PR %s on %s", pullrequest.number, arch)
        else:
            log.info("openQA tests for PR %s (build %s) are already covered", pullrequest.number, build)
            if self.comment:
                self.comment_on_pr(pullrequest, product, unique_version, arch, build)

    def comment_on_pr(self, pullrequest: PullRequest, product: str, version: str, arch: str, build: str) -> None:
        """Comment on PR if openQA results are available."""
        data = Data(pullrequest.number, "git", 0, self.flavor, arch, self.distri, version, build, product)

        try:
            jobs = self.openqa.get_jobs(data)
            for j in jobs:
                j.setdefault("build", build)
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
            self.gitea_repo,
            number=self.pr_number,
        )
        log.info(
            "Loaded %d active PRs from %s",
            len(open_prs),
            self.gitea_repo,
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

        for pr in self.prs:
            self.check_pullrequest(pr)

        return 0
