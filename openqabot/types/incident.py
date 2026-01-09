# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from collections import defaultdict
from logging import getLogger
from typing import Any

from openqabot.config import OBS_PRODUCTS
from openqabot.errors import EmptyChannelsError, EmptyPackagesError, NoRepoFoundError
from openqabot.loader import gitea
from openqabot.loader.repohash import get_max_revision

from .types import ArchVer, Repos

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
        skipped_products = set()
        for r in incident["channels"]:
            if not r.startswith("SUSE:SLFO"):
                continue
            val = r.split(":")
            if len(val) <= 3:
                continue
            obs_project = ":".join(val[2:-1])
            product = gitea.get_product_name(obs_project)
            if product in OBS_PRODUCTS:
                self.channels.append(Repos(":".join(val[0:2]), obs_project, *(val[-1].split("#"))))
            else:
                skipped_products.add(product)

        for product in sorted(skipped_products):
            log.info("Incident %s: Product %s is not in considered products", self.id, product)

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
        self._rev_cache_params: tuple[Any, Any] | None = None
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
    ) -> bool:
        params = (product_repo, product_version)
        if self._rev_cache_params == params:
            return self.revisions is not None

        self._rev_cache_params = params
        try:
            self.revisions = self._rev(self.channels, self.project, product_repo, product_version)
        except NoRepoFoundError:
            self.revisions = None
            return False
        else:
            return True

    def revisions_with_fallback(self, arch: str, ver: str) -> int | None:
        if self.revisions is None:
            self.compute_revisions_for_product_repo(None, None)
        try:
            arch_ver = ArchVer(arch, ver)
            # An unversioned SLE12 module will have ArchVer version "12"
            # but settings["VERSION"] can be any of "12","12-SP1" ... "12-SP5".
            if self.revisions is not None and arch_ver not in self.revisions and ver.startswith("12"):
                arch_ver = ArchVer(arch, "12")
            if self.revisions is None:
                log.debug("Incident %s: No revisions available", self.id)
                return None
            return self.revisions[arch_ver]
        except KeyError:
            log.debug("Incident %s: Architecture %s not found for version %s", self.id, arch, ver)
            return None

    @staticmethod
    def _rev(
        channels: list[Repos],
        project: str,
        product_repo: list[str] | str | None,
        product_version: str | None,
    ) -> dict[ArchVer, int]:
        rev: dict[ArchVer, int] = {}
        tmpdict: dict[ArchVer, list[tuple[str, str, str]]] = defaultdict(list)

        for repo in channels:
            version = repo.version
            if v := re.match(version_pattern, repo.version):
                version = v.group(0)

            ver = repo.product_version or version
            tmpdict[ArchVer(repo.arch, ver)].append((repo.product, repo.version, repo.product_version))

        last_product_repo = product_repo[-1] if isinstance(product_repo, list) else product_repo
        for archver, lrepos in tmpdict.items():
            max_rev = get_max_revision(lrepos, archver.arch, project, last_product_repo, product_version)
            if max_rev > 0:
                rev[archver] = max_rev

        if not rev:
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
        if any(p.startswith(("kernel-default", "kernel-source", "kernel-azure")) for p in packages):
            return False
        return any(p.startswith(("kgraft-patch-", "kernel-livepatch")) for p in packages)

    def contains_package(self, requires: list[str]) -> bool:
        return any(p != "kernel-livepatch-tools" and p.startswith(tuple(requires)) for p in self.packages)
