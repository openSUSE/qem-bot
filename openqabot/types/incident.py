# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import re
from logging import getLogger
from typing import Dict, List, Tuple

from . import ArchVer, Repos
from ..errors import EmptyChannels, EmptyPackagesError, NoRepoFoundError
from ..loader.repohash import get_max_revision

logger = getLogger("bot.types.incident")
version_pattern = re.compile(r"(\d+(?:[.-](?:SP)?\d+)?)")


class Incident:
    def __init__(self, incident):
        self.rr = incident["rr_number"]
        self.project = incident["project"]
        self.id = incident["number"]
        self.rrid = f"{self.project}:{self.rr}" if self.rr else None
        self.staging = not incident["inReview"]

        self.channels = [
            Repos(p, v, a)
            for p, v, a in (
                r.split(":")[2:]
                for r in incident["channels"]
                if r.startswith("SUSE:Updates") and "openSUSE-SLE" not in r
            )
            if p != "SLE-Module-Development-Tools-OBS"
        ]

        # set openSUSE-SLE arch as x86_64 by default
        # for now is simplification as we now test only on x86_64
        self.channels += [
            Repos(p, v, "x86_64")
            for p, v in (
                r.split(":")[2:]
                for r in (
                    i
                    for i in incident["channels"]
                    if i.startswith("SUSE:Updates") and "openSUSE-SLE" in i
                )
            )
        ]
        if not self.channels:
            raise EmptyChannels(self.project)

        self.packages = sorted(incident["packages"], key=len)
        if not self.packages:
            raise EmptyPackagesError(self.project)

        self.emu = incident["emu"]
        self.revisions = self._rev(self.channels, self.project)
        self.livepatch: bool = self._is_livepatch(self.packages)
        self.azure: bool = self._is_azure(self.packages)

    @staticmethod
    def _rev(channels: List[Repos], project: str) -> Dict[ArchVer, int]:
        rev: Dict[ArchVer, int] = {}
        tmpdict: Dict[ArchVer, List[Tuple[str, str]]] = {}

        for repo in channels:
            version = repo.version
            v = re.match(version_pattern, repo.version)
            if v:
                version = v.group(0)

            if ArchVer(repo.arch, version) in tmpdict:
                tmpdict[ArchVer(repo.arch, version)].append(
                    (repo.product, repo.version)
                )
            else:
                tmpdict[ArchVer(repo.arch, version)] = [(repo.product, repo.version)]

        if tmpdict:
            for archver, lrepos in tmpdict.items():
                try:
                    max_rev = get_max_revision(lrepos, archver.arch, project)
                    if max_rev > 0:
                        rev[archver] = max_rev
                except NoRepoFoundError as e:
                    raise e

        return rev

    def __repr__(self):
        if self.rrid:
            return f"<Incident: {self.rrid}>"
        return f"<Incident: {self.project}>"

    def __str__(self):
        return str(self.id)

    @staticmethod
    def _is_livepatch(packages: List[str]) -> bool:
        kgraft = False

        for package in packages:
            if (
                package.startswith("kernel-default")
                or package.startswith("kernel-source")
                or package.startswith("kernel-azure")
            ):
                return False
            if package.startswith("kgraft-patch-") or package.startswith(
                "kernel-livepatch"
            ):
                kgraft = True

        return kgraft

    def contains_package(self, requires: List[str]) -> bool:
        for package in self.packages:
            for req in requires:
                if package.startswith(req) and package != "kernel-livepatch-tools":
                    return True
        return False

    @staticmethod
    def _is_azure(packages) -> bool:
        """return True if package is kernel for MS AZURE"""
        for package in packages:
            if package.startswith("kernel-azure"):
                return True
        return False
