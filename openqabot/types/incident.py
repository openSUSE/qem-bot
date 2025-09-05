# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import re
from logging import getLogger
from typing import Dict, List, Tuple, Optional

from . import ArchVer, Repos
from ..errors import EmptyChannels, EmptyPackagesError, NoRepoFoundError
from ..loader.repohash import get_max_revision

log = getLogger("bot.types.incident")
version_pattern = re.compile(r"(\d+(?:[.-](?:SP)?\d+)?)")


class Incident:
    def __init__(self, incident):
        self.rr = incident["rr_number"]
        self.project = incident["project"]
        self.id = incident["number"]
        self.rrid = f"{self.project}:{self.rr}" if self.rr else None
        self.staging = not incident["inReview"]
        self.ongoing = (
            incident["isActive"]
            and incident["inReviewQAM"]
            and not incident["approved"]
        )
        self.embargoed = incident["embargoed"]
        self.priority = incident.get("priority")
        self.type = incident.get("type", "smelt")

        self.channels = [
            Repos(p, v, a)
            for p, v, a in (
                val
                for val in (
                    r.split(":")[2:]
                    for r in incident["channels"]
                    if r.startswith("SUSE:Updates")
                )
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
                for val in (
                    r.split(":")[2:]
                    for r in (
                        i for i in incident["channels"] if i.startswith("SUSE:Updates")
                    )
                )
                if len(val) == 2
            )
        ]
        # add channels for Gitea-based incidents
        self.channels += [
            Repos(":".join(val[0:2]), ":".join(val[2:-1]), *(val[-1].split("#")))
            for val in (
                r.split(":")
                for r in (i for i in incident["channels"] if i.startswith("SUSE:SLFO"))
            )
            if len(val) > 3
        ]

        # remove Manager-Server on aarch64 from channels
        self.channels = [
            chan
            for chan in self.channels
            if not (
                chan.product == "SLE-Module-SUSE-Manager-Server"
                and chan.arch == "aarch64"
            )
        ]

        if not self.channels:
            raise EmptyChannels(self.project)

        self.packages = sorted(incident["packages"], key=len)
        if not self.packages:
            raise EmptyPackagesError(self.project)

        self.emu = incident["emu"]
        self.revisions = None  # lazy-initialized via revisions_with_fallback()
        self.livepatch: bool = self._is_livepatch(self.packages)

    def compute_revisions_for_product_repo(self, product_repo: Optional[str]):
        self.revisions = self._rev(self.channels, self.project, product_repo)

    def revisions_with_fallback(self, arch: str, ver: str):
        if self.revisions is None:
            self.compute_revisions_for_product_repo(None)
        try:
            arch_ver = ArchVer(arch, ver)
            # An unversioned SLE12 module will have ArchVer version "12"
            # but settings["VERSION"] can be any of "12","12-SP1" ... "12-SP5".
            if arch_ver not in self.revisions and ver.startswith("12"):
                arch_ver = ArchVer(arch, "12")
            return self.revisions[arch_ver]
        except KeyError:
            log.debug("Incident %s does not have %s arch in %s", self.id, arch, ver)
            return None

    @staticmethod
    def _rev(
        channels: List[Repos], project: str, product_repo: Optional[str]
    ) -> Dict[ArchVer, int]:
        rev: Dict[ArchVer, int] = {}
        tmpdict: Dict[ArchVer, List[Tuple[str, str]]] = {}

        for repo in channels:
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
                max_rev = get_max_revision(lrepos, archver.arch, project, product_repo)
                if max_rev > 0:
                    rev[archver] = max_rev

        if len(rev) == 0:
            raise NoRepoFoundError
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
