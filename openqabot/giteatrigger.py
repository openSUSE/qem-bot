# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Trigger testing for PR(s) with certain label."""

from argparse import Namespace
from dataclasses import dataclass
from logging import getLogger
from typing import Any, cast

import requests
from openqa_client.exceptions import RequestError
from osc import conf

from openqabot import config
from openqabot.errors import NoResultsError
from openqabot.loader import gitea
from openqabot.loader.config import get_configs_from_path
from openqabot.loader.crawler import Crawler
from openqabot.loader.triggerconfig import TriggerConfig
from openqabot.repodiff import RepoDiff
from openqabot.types.isomatch import IsoMatch
from openqabot.types.pullrequest import PullRequest
from openqabot.types.types import Data

from .commenter import Commenter
from .loader.gitea import (
    approve_pr,
    get_open_prs,
    make_token_header,
)
from .openqa import OpenQAInterface

log = getLogger("bot.giteatrigger")

ISO_REGEX = (
    r"(?P<product>SLES)-(?P<version>[\d\.]+)-Online-"
    r"(?P<arch>x86_64)-Build(?P<build>[0-9\.]+)\.install.iso$"
)


@dataclass
class EvaluationResult:
    """Result of evaluating a pull request config."""

    triggered: bool
    data: Data | None = None


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
            args.configs, "trigger_config", TriggerConfig.from_config_entry
        )
        if not self.config_list:
            error_msg = "No configs were found"
            raise ValueError(error_msg)
        self.pr_number: int = args.pr_number
        self.openqa: OpenQAInterface = OpenQAInterface()
        self.is_maintenance = bool(getattr(args, "maintenance", False))
        if not self.is_maintenance:
            self.pr_required_labels: set[str] = set(args.pr_label.split(","))
        self.prs: dict[str, list[PullRequest]] = {}
        self.comment: bool = getattr(args, "comment", False)
        self.commenter: Commenter = Commenter(args, submissions=[])
        self.repodiff: RepoDiff = RepoDiff(args)
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

    def _should_skip_pr(self, pullrequest: PullRequest, trigger_config: TriggerConfig) -> bool:
        """Determine if a pull request should be skipped based on branch or status/labels."""
        if pullrequest.branch != trigger_config.branch:
            log.info("PR %s does not match requested branch(%s)", pullrequest, trigger_config.branch)
            return True

        if self.is_maintenance:
            if not self.is_build_finished(pullrequest, trigger_config):
                log.debug("PR %s disregarded (build not finished in Gitea)", pullrequest.number)
                return True
        elif not pullrequest.has_all_labels(self.pr_required_labels):
            log.debug("PR %s disregarded (labels: %s)", pullrequest.number, pullrequest.labels)
            return True

        return False

    def _get_matched_iso(
        self, pullrequest: PullRequest, trigger_config: TriggerConfig, repo_url: str
    ) -> tuple[IsoMatch, str | None]:
        """Extract version and build info into an IsoMatch and its raw filename."""
        if self.is_maintenance:
            try:
                staged_update_name = self.repodiff.get_staged_update_name(repo_url)
            except NoResultsError as e:
                err_msg = f"No staged update name found for PR {pullrequest.number} in {repo_url}"
                raise NoResultsError(err_msg) from e
            matched_iso = IsoMatch(
                trigger_config.project,
                trigger_config.get_branch_version(),
                f":{trigger_config.get_build_project()}:{pullrequest.number}:{staged_update_name}",
            )
            return matched_iso, None

        if matched_iso_regex := Crawler(verify=not config.settings.insecure).get_regex_match_from_url(
            repo_url, ISO_REGEX
        ):
            return IsoMatch.from_regex_match(matched_iso_regex, pullrequest.number), matched_iso_regex.group(0)

        err_msg = f"No ISO found for PR {pullrequest.number} in {repo_url}"
        raise NoResultsError(err_msg)

    def _build_openqa_settings(
        self,
        pullrequest: PullRequest,
        trigger_config: TriggerConfig,
        matched_iso: IsoMatch,
        repo_url: str,
        iso_name: str | None,
    ) -> dict[str, str]:
        """Construct settings dictionary for posting a job to openQA."""
        settings = {
            "BUILD": matched_iso.build,
            "VERSION": matched_iso.version,
            "DISTRI": trigger_config.distri,
            "ARCH": matched_iso.arch,
            "FLAVOR": trigger_config.flavor,
            "_GITEA_PR": str(pullrequest.number),
            "GITEA_SHA": pullrequest.commit_sha,
            "GITEA_PR_URL": pullrequest.url,
            "GITEA_REPO": pullrequest.project,
        }

        if self.is_maintenance:
            settings["INCIDENT_REPO"] = repo_url
            settings["OS_TEST_TEMPLATE"] = trigger_config.get_os_template_setting()
            settings["GITEA_STATUSES_URL"] = gitea.commit_status_url(pullrequest)
            settings["webhook_id"] = pullrequest.generate_webhook_id()
        elif iso_name is not None:
            settings |= GiteaTrigger.generate_medium_vars(trigger_config, repo_url, pullrequest.number, iso_name)

        return settings

    def check_pullrequest(self, pullrequest: PullRequest) -> None:
        """Evaluate a pull request and trigger openQA tests if new artifacts are available.

        The method constructs the repository URL, extracts the build version from
        the available ISO artifacts using regex, and checks if this specific
        build has already been tested. If testing is required, it posts a new
        job to openQA with the relevant configuration.

        Args:
            pullrequest (PullRequest): The pull request object to validate and test.

        """
        applicable_configs = [
            tc
            for tc in self.config_list
            if tc.project == pullrequest.project and not self._should_skip_pr(pullrequest, tc)
        ]
        if not applicable_configs:
            log.debug("No applicable configs found for PR %s in project %s", pullrequest.number, pullrequest.project)
            return

        log.info("Evaluating PR %s for openQA triggering", pullrequest.number)

        outcomes = [res for tc in applicable_configs if (res := self._evaluate_config(pullrequest, tc)) is not None]

        any_triggered = any(outcome.triggered for outcome in outcomes)
        covered_data = [outcome.data for outcome in outcomes if outcome.data is not None]

        if self.comment and covered_data and not any_triggered:
            self.comment_on_pr(pullrequest, covered_data)

    def _evaluate_config(self, pullrequest: PullRequest, trigger_config: TriggerConfig) -> EvaluationResult | None:
        """Trigger openQA for one config, or return its coverage Data."""
        repo_url = trigger_config.generate_obs_repo_url(
            pullrequest.number, config.settings.obs_download_url, is_maintenance=self.is_maintenance
        )
        try:
            matched_iso, iso_name = self._get_matched_iso(pullrequest, trigger_config, repo_url)
        except NoResultsError as e:
            log.warning(str(e))
            return None

        if self.is_openqa_triggering_needed(matched_iso, trigger_config):
            openqa_settings = self._build_openqa_settings(pullrequest, trigger_config, matched_iso, repo_url, iso_name)
            self.openqa.post_job(openqa_settings)
            log.info("Triggered openQA tests for PR %s on %s", pullrequest.number, matched_iso.arch)
            return EvaluationResult(triggered=True)

        log.info(
            "openQA tests for PR %s (build %s, flavor %s) are already covered",
            pullrequest.number,
            matched_iso.build,
            trigger_config.flavor,
        )
        data = Data.from_trigger_config_and_matched_iso(trigger_config, matched_iso, pullrequest.number)
        return EvaluationResult(triggered=False, data=data)

    @staticmethod
    def generate_medium_vars(
        trigger_config: TriggerConfig, repo_url: str, pr_number: int, iso_name: str
    ) -> dict[str, str]:
        """Generate HDD or ISO media parameters for trigger settings."""
        # Add HDD parameters if image_regex is configured, otherwise use ISO
        if trigger_config.image_regex:
            # Images are in /images/ directory instead of /product/iso/
            images_url = repo_url.replace("/product/iso", "/images")
            matched_image_regex = Crawler(verify=not config.settings.insecure).get_regex_match_from_url(
                images_url, trigger_config.image_regex
            )
            if matched_image_regex:
                return {
                    "HDD_1_URL": f"{images_url}/{matched_image_regex.group(0)}",
                    "HDD_1": matched_image_regex.group(0),
                }
            log.warning(
                "No image found matching regex '%s' for PR %s in %s",
                trigger_config.image_regex,
                pr_number,
                images_url,
            )
        # No image_regex configured, use ISO parameters
        return {"ISO_1_URL": f"{repo_url}/{iso_name}", "ISO_1": iso_name}

    def comment_on_pr(self, pullrequest: PullRequest, data_list: list[Data]) -> None:
        """Comment on PR if openQA results are available."""
        try:
            # build first so an existing job "build" overrides it (setdefault semantics)
            all_jobs = [{"build": data.build, **job} for data in data_list for job in self.openqa.get_jobs(data)]
        except (requests.exceptions.RequestException, RequestError):
            log.exception("Failed to fetch jobs for PR %s; aborting approval", pullrequest.number)
            return

        if res := self.commenter.generate_comment(pullrequest, all_jobs):
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

    def is_build_finished(self, pr: PullRequest, trigger_config: TriggerConfig) -> bool:
        """Check if build is finished for a pull request.

        Args:
            pr (PullRequest): The pull request to check.
            trigger_config (TriggerConfig): The triggering configuration.

        Returns:
            bool: True if build is finished, False otherwise.

        """
        pr_name = f"{trigger_config.project}#{pr.number}"
        try:
            pr_events = gitea.get_events_by_timeline(self.gitea_token, trigger_config.project, pr.number)
        except requests.exceptions.RequestException:
            log.exception("Failed to fetch build status/events from Gitea for PR %s", pr_name)
            return False
        if not pr_events:
            log.warning("No events found for %s", pr_name)
            return False
        bot_events = pr_events.get(cast("str", config.settings.git_review_bot_user))
        if not bot_events:
            log.warning("User %s has no events on %s", config.settings.git_review_bot_user, pr_name)
            return False

        review = cast(
            "dict[str, Any]",
            gitea.get_json(
                gitea.review_url(
                    trigger_config.project,
                    pr.number,
                    bot_events["review"]["review_id"],
                ),
                self.gitea_token,
            ),
        )

        if review["state"] != "APPROVED":
            log.warning("Build is in state %s for %s", review["state"], pr_name)
            return False

        if review["body"] == "Build successful":
            log.info("Build is finished for %s", pr_name)
            return True

        if review["body"] == "No package changes, not rebuilding project by default, accepting change":
            log.info("No build has been triggered for %s", pr_name)
        else:
            log.error("Unknown build state for %s: %s", pr_name, review["body"])

        return False

    def load_prs_for_project(self, project: str) -> None:
        """Load open pull requests for a specific project.

        Args:
            project (str): The project name to load pull requests for.

        """
        if project in self.prs:
            return
        self.prs[project] = get_open_prs(self.gitea_token, project, number=self.pr_number)
        log.info("Loaded %d active PRs from %s", len(self.prs[project]), project)

    def __call__(self) -> int:
        """Run test triggering logic.

        Returns:
            int: 0 if all went well

        """
        for trigger_config in self.config_list:
            self.load_prs_for_project(trigger_config.project)
        distinct_prs = list(
            {(pr.project, pr.number): pr for tc in self.config_list for pr in self.prs.get(tc.project, [])}.values()
        )
        for pr in distinct_prs:
            self.check_pullrequest(pr)

        return 0
