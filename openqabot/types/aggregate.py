# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Aggregate type definition."""

from __future__ import annotations

import datetime
from collections import defaultdict
from itertools import chain
from logging import getLogger
from typing import TYPE_CHECKING, Any, NamedTuple

import requests

from openqabot import config
from openqabot.dashboard import get_json
from openqabot.errors import NoTestIssuesError, SameBuildExistsError
from openqabot.loader.repohash import merge_repohash
from openqabot.pc_helper import apply_pc_tools_image, apply_publiccloud_pint_image
from openqabot.utc import UTC

from .baseconf import BaseConf, JobConfig
from .types import ProdVer, Repos

if TYPE_CHECKING:
    from .submission import Submission

log = getLogger("bot.types.aggregate")


class PostData(NamedTuple):
    """Data to be posted to dashboard."""

    test_submissions: defaultdict[str, list[Submission]]
    test_repos: defaultdict[str, list[str]]
    repohash: str
    build: str


class Aggregate(BaseConf):
    """Aggregate job configuration and processing."""

    def __init__(self, config: JobConfig) -> None:
        """Initialize the Aggregate class."""
        super().__init__(config)
        self.flavor = config.config["FLAVOR"]
        self.archs = config.config["archs"]
        self.onetime = config.config.get("onetime", False)
        self.test_issues = self.normalize_repos(config.config)

    @staticmethod
    def normalize_repos(config: dict[str, Any]) -> dict[str, ProdVer]:
        """Normalize repository configuration from config.settings."""
        try:
            return {key: ProdVer(*value.split(":")) for key, value in config["test_issues"].items()}
        except KeyError as e:
            raise NoTestIssuesError from e

    def __repr__(self) -> str:
        """Return a string representation of the Aggregate."""
        return f"<Aggregate product: {self.product}>"

    @staticmethod
    def get_buildnr(repohash: str, old_repohash: str, build: str) -> str:
        """Determine the next build number based on current date and repohash."""
        today = datetime.datetime.now(tz=UTC).date().strftime("%Y%m%d")

        if build.startswith(today) and repohash == old_repohash:
            raise SameBuildExistsError

        counter = int(build.rsplit("-", maxsplit=1)[-1]) + 1 if build.startswith(today) else 1
        return f"{today}-{counter}"

    def filter_submissions(self, submissions: list[Submission]) -> list[Submission]:
        """Filter out submissions that are not suitable for aggregate tests."""

        def is_valid(submission: Submission) -> bool:
            if any((submission.livepatch, submission.staging)):
                return False
            if self.filter_embargoed(self.flavor) and submission.embargoed:
                log.debug("Submission %s skipped: Embargoed and embargo-filtering enabled", submission)
                return False
            return True

        return [s for s in submissions if is_valid(s)]

    def get_test_submissions_and_repos(
        self, valid_submissions: list[Submission], issues_arch: str
    ) -> tuple[defaultdict[str, list[Submission]], defaultdict[str, list[str]]]:
        """Group submissions and their repository URLs for testing."""
        test_submissions = defaultdict(list)
        test_repos = defaultdict(list)

        for sub in valid_submissions:
            for issue, template in self.test_issues.items():
                if Repos(template.product, template.version, issues_arch) in sub.channels:
                    test_submissions[issue].append(sub)

        for issue, subs in test_submissions.items():
            tmpl = issue.replace("ISSUES", "REPOS")
            test_repos[tmpl].extend(self._get_repo_url(sub, issue, issues_arch) for sub in subs)
        return test_submissions, test_repos

    def _get_repo_url(self, sub: Submission, issue: str, issues_arch: str) -> str:
        """Construct the repository URL for a submission."""
        product = self.test_issues[issue].product
        version = self.test_issues[issue].version
        base_url = f"{config.settings.download_maintenance}{sub.id}/SUSE_Updates_{product}_{version}"
        return f"{base_url}/" if product.startswith("openSUSE") else f"{base_url}_{issues_arch}/"

    def _apply_public_cloud_settings(self, settings: dict[str, Any]) -> dict[str, Any] | None:
        """Apply Public Cloud specific settings if present."""
        if "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY" in settings:
            settings = apply_pc_tools_image(settings)
            if not settings or not settings.get("PUBLIC_CLOUD_TOOLS_IMAGE_BASE", False):
                log.info("No tools image found for %s", self)
                return None

        if "PUBLIC_CLOUD_PINT_QUERY" in settings:
            settings = apply_publiccloud_pint_image(settings)
            if not settings or not settings.get("PUBLIC_CLOUD_IMAGE_ID", False):
                log.info("No PINT image found for %s", self)
                return None
        return settings

    def _add_incident_data(self, full_post: dict[str, Any], data: PostData) -> None:  # noqa: PLR6301
        """Add incident-specific data to the dashboard post."""
        for template, issues in data.test_submissions.items():
            full_post["openqa"][template] = ",".join(str(x.id) for x in issues)
            full_post["qem"]["incidents"] += issues
        for template, issues in data.test_repos.items():
            full_post["openqa"][template] = ",".join(issues)

        # Remove duplicates while preserving Submission objects
        seen = set()
        unique_incidents = []
        for sub in full_post["qem"]["incidents"]:
            if sub.id not in seen:
                seen.add(sub.id)
                unique_incidents.append(sub)
        full_post["qem"]["incidents"] = unique_incidents

    def _finalize_post(self, full_post: dict[str, Any], arch: str) -> None:
        """Finalize the dashboard post with metadata and summary information."""
        full_post["openqa"]["__DASHBOARD_INCIDENTS_URL"] = ",".join(
            f"{config.settings.qem_dashboard_url}incident/{sub.id}" for sub in full_post["qem"]["incidents"]
        )
        full_post["openqa"]["__SMELT_INCIDENTS_URL"] = ",".join(
            f"{config.settings.smelt_url}/incident/{sub.id}"
            for sub in full_post["qem"]["incidents"]
            if sub.type == config.settings.default_submission_type
        )

        full_post["qem"]["settings"] = full_post["openqa"]
        full_post["qem"]["repohash"] = full_post["openqa"]["REPOHASH"]
        full_post["qem"]["build"] = full_post["openqa"]["BUILD"]
        full_post["qem"]["arch"] = arch
        full_post["qem"]["product"] = self.product
        full_post["qem"]["incidents"] = [sub.id for sub in full_post["qem"]["incidents"]]

    def create_full_post(
        self,
        arch: str,
        data: PostData,
        ci_url: str | None,
    ) -> dict[str, Any] | None:
        """Create the full post data for the dashboard."""
        full_post: dict[str, Any] = {
            "openqa": {"REPOHASH": data.repohash, "BUILD": data.build},
            "qem": {"incidents": [], "settings": {}},
            "api": "api/update_settings",
        }
        if ci_url:
            full_post["openqa"]["__CI_JOB_URL"] = ci_url

        settings_data = self._apply_public_cloud_settings(self.settings.copy())
        if settings_data is None:
            return None

        full_post["openqa"].update(settings_data)
        full_post["openqa"]["FLAVOR"] = self.flavor
        full_post["openqa"]["ARCH"] = arch
        full_post["openqa"]["_DEPRIORITIZEBUILD"] = 1

        if config.settings.deprioritize_limit is not None:
            full_post["openqa"]["_DEPRIORITIZE_LIMIT"] = config.settings.deprioritize_limit

        self._add_incident_data(full_post, data)

        if not full_post["qem"]["incidents"]:
            return None

        if max_prio := max(
            (s.priority for s in chain.from_iterable(data.test_submissions.values()) if s.priority is not None),
            default=0,
        ):
            full_post["openqa"]["_PRIORITY"] = config.settings.base_prio - (max_prio // config.settings.priority_scale)

        self._finalize_post(full_post, arch)
        return full_post

    def process_arch(
        self,
        arch: str,
        valid_submissions: list[Submission],
        token: dict[str, str],
        ci_url: str | None,
        *,
        ignore_onetime: bool,
    ) -> dict[str, Any] | None:
        """Process a specific architecture for aggregate jobs."""
        # Temporary workaround for applying the correct architecture on jobs, which use a helper VM
        issues_arch = self.settings.get("TEST_ISSUES_ARCH", arch)

        test_submissions, test_repos = self.get_test_submissions_and_repos(valid_submissions, issues_arch)

        repohash = merge_repohash(
            sorted({str(sub.id) for sub in chain.from_iterable(test_submissions.values())}),
        )

        try:
            old_jobs = get_json(
                "api/update_settings",
                params={"product": self.product, "arch": arch},
                headers=token,
            )
        except requests.exceptions.JSONDecodeError:
            log.exception("Dashboard API error: Invalid JSON received for aggregate jobs")
            old_jobs = None
        except requests.exceptions.RequestException:
            log.exception("Dashboard API error: Could not fetch previous aggregate jobs")
            old_jobs = None

        if not old_jobs:
            log.info("No aggregate jobs found for %s on arch %s", self, arch)
            return None

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
                "Aggregate for %s on %s skipped: A build with the same RepoHash already exists",
                self.product,
                arch,
            )
            return None

        if not ignore_onetime and (self.onetime and build.split("-")[-1] != "1"):
            return None

        return self.create_full_post(
            arch,
            PostData(test_submissions, test_repos, repohash, build),
            ci_url,
        )

    def __call__(
        self,
        submissions: list[Submission],
        token: dict[str, str],
        ci_url: str | None,
        *,
        ignore_onetime: bool = False,
    ) -> list[dict[str, Any]]:
        """Process all architectures and return a list of posts for the dashboard."""
        valid_submissions = self.filter_submissions(submissions)

        results = [
            self.process_arch(arch, valid_submissions, token, ci_url, ignore_onetime=ignore_onetime)
            for arch in self.archs
        ]

        return [res for res in results if res is not None]
