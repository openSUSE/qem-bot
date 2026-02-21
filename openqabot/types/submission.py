# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Submission type definition."""

from __future__ import annotations

import re
from collections import defaultdict
from logging import getLogger
from typing import Any, cast

from openqabot import config
from openqabot.errors import EmptyChannelsError, EmptyPackagesError, NoRepoFoundError
from openqabot.loader import gitea
from openqabot.loader.repohash import RepoOptions, get_max_revision

from .types import ArchVer, Repos

log = getLogger("bot.types.submission")
version_pattern = re.compile(r"(\d+(?:[.-](?:SP)?\d+)?)")


class Submission:
    """Information about a submission."""

    def __init__(self, submission: dict[str, Any]) -> None:
        """Initialize the Submission class."""
        self.rr: int | None = submission["rr_number"]
        self.project: str = submission["project"]
        self.id: int = submission["number"]
        self.rrid: str | None = f"{self.project}:{self.rr}" if self.rr else None
        self.staging: bool = not submission["inReview"]
        self.ongoing: bool = submission["isActive"] and submission["inReviewQAM"] and not submission["approved"]
        self.embargoed: bool = submission["embargoed"]
        self.priority: int | None = submission.get("priority")
        self.type: str = submission.get("type") or config.settings.default_submission_type

        self.channels: list[Repos] = [
            Repos(p, v, a)
            for p, v, a in (
                val
                for val in (r.split(":")[2:] for r in submission["channels"] if r.startswith("SUSE:Updates"))
                if len(val) == 3  # noqa: PLR2004
            )
            if p != "SLE-Module-Development-Tools-OBS"
        ]
        # set openSUSE-SLE arch as x86_64 by default
        # for now is simplification as we now test only on x86_64
        self.channels += [
            Repos(p, v, "x86_64")
            for p, v in (
                val
                for val in (
                    r.split(":")[2:] for r in (i for i in submission["channels"] if i.startswith("SUSE:Updates"))
                )
                if len(val) == 2  # noqa: PLR2004
            )
        ]
        # add channels for Gitea-based submissions
        self.skipped_products = set()
        for r in submission["channels"]:
            if not r.startswith("SUSE:SLFO"):
                continue
            val = r.split(":")
            if len(val) <= 3:  # noqa: PLR2004
                continue
            obs_project = ":".join(val[2:-1])
            product = gitea.get_product_name(obs_project)
            if "all" in config.settings.obs_products_set or product in config.settings.obs_products_set:
                self.channels.append(Repos(":".join(val[0:2]), obs_project, *(val[-1].split("#"))))
            else:
                self.skipped_products.add(product)

        self._logged_skipped = False

        # remove Manager-Server on aarch64 from channels
        self.channels = [
            chan
            for chan in self.channels
            if not (chan.product == "SLE-Module-SUSE-Manager-Server" and chan.arch == "aarch64")
        ]

        if not self.channels:
            raise EmptyChannelsError(self.project)

        self.packages: list[str] = cast("list[str]", sorted(submission["packages"], key=len))
        if not self.packages:
            raise EmptyPackagesError(self.project)

        self.emu: bool = submission["emu"]
        self.revisions: dict[ArchVer, int] | None = None  # lazy-initialized via revisions_with_fallback()
        self.rev_cache_params: tuple[Any, ...] | None = None
        self.rev_logged: bool = False
        self.livepatch: bool = self.is_livepatch(self.packages)

    def log_skipped(self) -> None:
        """Log products that were skipped during channel initialization."""
        if self._logged_skipped:
            return
        for product in sorted(self.skipped_products):
            log.info("Submission %s: Product %s is not in considered products", self, product)
        self._logged_skipped = True

    @classmethod
    def create(cls, data: dict) -> Submission | None:
        """Create a Submission instance from a dictionary, handling errors."""
        sub_id = f"{data.get('type') or config.settings.default_submission_type}:{data.get('number')}"
        try:
            return cls(data)
        except EmptyChannelsError:
            log.info("Submission %s ignored: No channels found for project %s", sub_id, data.get("project"))
            return None
        except EmptyPackagesError:
            log.info("Submission %s ignored: No packages found for project %s", sub_id, data.get("project"))
            return None

    def compute_revisions_for_product_repo(
        self,
        product_repo: list[str] | str | None,
        product_version: str | None,
        limit_archs: set[str] | None = None,
    ) -> bool:
        """Calculate repohashes for all channels of this submission."""
        params = (product_repo, product_version, frozenset(limit_archs) if limit_archs else None)
        if self.rev_cache_params == params:
            return self.revisions is not None

        self.rev_cache_params = params
        product_name = product_repo[-1] if isinstance(product_repo, list) else product_repo
        opts = RepoOptions(product_name, product_version, str(self))

        try:
            self.revisions = self.rev(
                self.channels,
                self.project,
                opts,
                limit_archs,
            )
        except NoRepoFoundError as e:
            if not self.rev_logged:
                msg = "Submission %s skipped: RepoHash calculation failed for project %s"
                msg = f"{msg}: {e}" if len(str(e)) > 0 else msg
                log.info(msg, self, self.project)
                self.rev_logged = True
            self.revisions = None
            return False
        else:
            return True

    def revisions_with_fallback(self, arch: str, ver: str) -> int | None:
        """Return the repohash for a specific architecture and version, with fallback for SLE12."""
        if self.revisions is None:
            self.compute_revisions_for_product_repo(None, None)
        try:
            arch_ver = ArchVer(arch, ver)
            # An unversioned SLE12 module will have ArchVer version "12"
            # but settings["VERSION"] can be any of "12","12-SP1" ... "12-SP5".
            if self.revisions is not None and arch_ver not in self.revisions and ver.startswith("12"):
                arch_ver = ArchVer(arch, "12")
            if self.revisions is None:
                log.debug("Submission %s: No revisions available", self)
                return None
            return self.revisions[arch_ver]
        except KeyError:
            log.debug("Submission %s: Architecture %s not found for version %s", self, arch, ver)
            return None

    @staticmethod
    def rev(
        channels: list[Repos],
        project: str,
        options: RepoOptions,
        limit_archs: set[str] | None = None,
    ) -> dict[ArchVer, int]:
        """Calculate repohashes for a set of channels."""
        rev: dict[ArchVer, int] = {}
        tmpdict: dict[ArchVer, list[Repos]] = defaultdict(list)

        for repo in channels:
            if limit_archs and repo.arch not in limit_archs:
                continue
            version = repo.version
            if v := re.match(version_pattern, repo.version):
                version = v.group(0)

            ver = repo.product_version or version

            if options.product_version and ver != options.product_version:
                continue

            tmpdict[ArchVer(repo.arch, ver)].append(repo)

        for archver, lrepos in tmpdict.items():
            repos_to_check = lrepos
            if project == "SLFO" and options.product_name:
                filtered_repos = [
                    r for r in lrepos if options.product_name.startswith(gitea.get_product_name(r.version))
                ]
                if not filtered_repos:
                    continue
                repos_to_check = filtered_repos

            max_rev = get_max_revision(repos_to_check, archver.arch, project, options)
            if max_rev > 0:
                rev[archver] = max_rev

        if not rev:
            raise NoRepoFoundError
        return rev

    def __repr__(self) -> str:
        """Return a representation of the Submission."""
        if self.rrid:
            return f"<Submission: {self.type}:{self.rrid}>"
        return f"<Submission: {self.type}:{self.project}>"

    def __str__(self) -> str:
        """Return a string representation of the Submission."""
        return f"{self.type}:{self.id}"

    @staticmethod
    def is_livepatch(packages: list[str]) -> bool:
        """Check if a list of packages contains livepatch related ones."""
        if any(p.startswith(("kernel-default", "kernel-source", "kernel-azure")) for p in packages):
            return False
        return any(p.startswith(("kgraft-patch-", "kernel-livepatch")) for p in packages)

    def contains_package(self, requires: list[str]) -> bool:
        """Check if the submission contains any of the required packages."""
        return any(p != "kernel-livepatch-tools" and p.startswith(tuple(requires)) for p in self.packages)
