# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from logging import getLogger
from typing import Any

from openqabot.errors import EmptyChannelsError, EmptyPackagesError, NoRepoFoundError
from openqabot.loader.repohash import get_max_revision

from . import ArchVer, Repos

log = getLogger("bot.types.incident")
version_pattern = re.compile(r"(\d+(?:[.-](?:SP)?\d+)?)")


class Incident:
    def __init__(self, incident: dict[str, Any]) -> None:
        self.rr: int | None = incident["rr_number"]
        self.project: str = incident["project"]
        self.id: int = incident["number"]
        self.rrid: str | None = f"{self.project}:{self.rr}" if self.rr else None
        self.staging: bool = not incident["inReview"]
        self.ongoing: bool = incident["isActive"] and incident["inReviewQAM"] and not incident["approved"]
        self.embargoed: bool = incident["embargoed"]
        self.priority: int | None = incident.get("priority")
        self.type: str = incident.get("type", "smelt")
        self.arch_filter: list[str] | None = None

        self.channels: list[Repos] = [
            Repos(p, v, a)
            for p, v, a in (
                val
                for val in (r.split(":")[2:] for r in incident["channels"] if r.startswith("SUSE:Updates"))
                if len(val) == 3
            )
            if p != "SLE-Module-Development-Tools-OBS"
        ]
        # set openSUSE-SLE arch as x86_64 by default
        # for now is simplification as we now test only on x86_64
        self.channels += [
            Repos(p, v, "x86_64")
            for p, v in (
                val
                for val in (r.split(":")[2:] for r in (i for i in incident["channels"] if i.startswith("SUSE:Updates")))
                if len(val) == 2
            )
        ]
        # add channels for Gitea-based incidents
        self.channels += [
            Repos(":".join(val[0:2]), ":".join(val[2:-1]), *(val[-1].split("#")))
            for val in (r.split(":") for r in (i for i in incident["channels"] if i.startswith("SUSE:SLFO")))
            if len(val) > 3
        ]

        # remove Manager-Server on aarch64 from channels
        self.channels = [
            chan
            for chan in self.channels
            if not (chan.product == "SLE-Module-SUSE-Manager-Server" and chan.arch == "aarch64")
        ]

        if not self.channels:
            raise EmptyChannelsError(self.project)

        self.packages: list[str] = sorted(incident["packages"], key=len)
        if not self.packages:
            raise EmptyPackagesError(self.project)

        self.emu: bool = incident["emu"]
        self.revisions: dict[ArchVer, int] | None = None  # lazy-initialized via revisions_with_fallback()
        self.livepatch: bool = self._is_livepatch(self.packages)

    @classmethod
    def create(cls, data: dict) -> Incident | None:
        try:
            return cls(data)
        except EmptyChannelsError:
            log.info("Incident %s ignored: No channels found for project %s", data.get("number"), data.get("project"))
            return None
        except EmptyPackagesError:
            log.info("Incident %s ignored: No packages found for project %s", data.get("number"), data.get("project"))
            return None

    def compute_revisions_for_product_repo(
        self,
        product_repo: list[str] | str | None,
        product_version: str | None,
    ) -> None:
        self.revisions = self._rev(self.arch_filter, self.channels, self.project, product_repo, product_version)

    def revisions_with_fallback(self, arch: str, ver: str) -> int | None:
        if self.revisions is None:
            self.compute_revisions_for_product_repo(None, None)
        try:
            arch_ver = ArchVer(arch, ver)
            # An unversioned SLE12 module will have ArchVer version "12"
            # but settings["VERSION"] can be any of "12","12-SP1" ... "12-SP5".
            if arch_ver not in self.revisions and ver.startswith("12"):
                arch_ver = ArchVer(arch, "12")
            return self.revisions[arch_ver]
        except KeyError:
            log.debug("Incident %s: Architecture %s not found for version %s", self.id, arch, ver)
            return None

    @staticmethod
    def _rev(
        arch_filter: list[str] | None,
        channels: list[Repos],
        project: str,
        product_repo: list[str] | str | None,
        product_version: str | None,
    ) -> dict[ArchVer, int]:
        rev: dict[ArchVer, int] = {}
        tmpdict: dict[ArchVer, list[tuple[str, str, str]]] = {}

        for repo in channels:
            if arch_filter is not None and repo.arch not in arch_filter:
                continue
            version = repo.version
            v = re.match(version_pattern, repo.version)
            if v:
                version = v.group(0)

            repo_info = (repo.product, repo.version, repo.product_version)
            ver = repo.product_version or version
            arch_ver = ArchVer(repo.arch, ver)
            if arch_ver in tmpdict:
                tmpdict[arch_ver].append(repo_info)
            else:
                tmpdict[arch_ver] = [repo_info]

        if tmpdict:
            for archver, lrepos in tmpdict.items():
                last_product_repo = product_repo[-1] if isinstance(product_repo, list) else product_repo
                max_rev = get_max_revision(
                    lrepos,
                    archver.arch,
                    project,
                    last_product_repo,
                    product_version,
                )
                if max_rev > 0:
                    rev[archver] = max_rev

        if len(rev) == 0:
            raise NoRepoFoundError
        return rev

    def __repr__(self) -> str:
        if self.rrid:
            return f"<Incident: {self.rrid}>"
        return f"<Incident: {self.project}>"

    def __str__(self) -> str:
        return str(self.id)

    @staticmethod
    def _is_livepatch(packages: list[str]) -> bool:
        kgraft = False

        for package in packages:
            if package.startswith(("kernel-default", "kernel-source", "kernel-azure")):
                return False
            if package.startswith(("kgraft-patch-", "kernel-livepatch")):
                kgraft = True

        return kgraft

    def contains_package(self, requires: list[str]) -> bool:
        for package in self.packages:
            for req in requires:
                if package.startswith(req) and package != "kernel-livepatch-tools":
                    return True
        return False
