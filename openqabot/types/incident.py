from logging import getLogger
from typing import Dict, List, Tuple

from ..errors import EmptyChannels, NoRepoFoundError
from ..loader.repohash import get_max_revision
from . import Repos

logger = getLogger("bot.types.incident")


class Incident:
    def __init__(self, incident):
        self.rr = incident["rr_number"]
        self.project = incident["project"]
        self.id = incident["number"]
        self.rrid = f"{self.project}:{self.rr}" if self.rr else None
        self.staging = not bool(self.rr)
        self.channels = [
            Repos(p, v, a)
            for p, v, a in (
                r.split(":")[2:]
                for r in incident["channels"]
                if r.startswith("SUSE:Updates") and not "openSUSE-SLE" in r
            )
            if p != "SLE-Module-Development-Tools-OBS"
        ]
        if not self.channels:
            raise EmptyChannels(self.project)
        self.packages = sorted(incident["packages"], key=len)
        self.emu = incident["emu"]
        self.revisions = self._rev(self.channels, self.project)
        self.livepatch: bool = self._is_livepatch(self.packages)
        self.azure: bool = self._is_azure(self.packages)

    @staticmethod
    def _rev(channels: List[Repos], project: str) -> Dict[str, int]:
        rev: Dict[str, int] = {}
        tmpdict: Dict[str, List[Tuple[str, str]]] = {}

        for repo in channels:
            if repo.arch in rev:
                tmpdict[repo.arch].append((repo.product, repo.version))
            else:
                tmpdict[repo.arch] = [(repo.product, repo.version)]

        if tmpdict:
            for arch, lrepos in tmpdict.items():
                try:
                    rev[arch] = get_max_revision(lrepos, arch, project)
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
    def _is_azure(packages):
        """ return True if package is kernel for MS AZURE """
        for package in packages:
            if package.startswith("kernel-azure"):
                return True
        return False
