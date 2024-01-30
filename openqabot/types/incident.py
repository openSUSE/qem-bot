# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import re
from logging import getLogger, DEBUG as LOG_DEBUG_LEVEL
from typing import Dict, List, Tuple
from openqabot.utils import retry3 as requests

# Make sure we have the right dashboard URL
from .. import QEM_DASHBOARD
from . import ArchVer, Repos
from ..errors import EmptyChannels, EmptyPackagesError, NoRepoFoundError, NoResultsError
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
        self.embargoed = incident["embargoed"]
        self.priority = incident.get("priority")

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
        self.revisions = self._rev(self.channels, self.project)
        self.livepatch: bool = self._is_livepatch(self.packages)

    def revisions_with_fallback(self, arch: str, ver: str):
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

    def has_failures(self, token) -> bool:
        results = requests.get(
            QEM_DASHBOARD + "/api/jobs/incident/" + str(self.id), headers=token
        ).json()

        failed_jobs = [res for res in results if res["status"] != "passed"]
        if failed_jobs:
            log.info("Found %s failed jobs for incident %s:", len(failed_jobs), self.id)
            # if debug is enabled, print all failed jobs
            if log.isEnabledFor(LOG_DEBUG_LEVEL):
                log_debug = lambda job_id: log.debug(
                    "Job %s is not marked as acceptable for incident %s",
                    job_id,
                    self.id,
                )
                [log_debug(res["job_id"]) for res in failed_jobs]

        if not results:
            raise NoResultsError(
                "Job setting %s not found for incident" % (str(self.id))
            )

        # Return true if there are any failed jobs, so if results is not empty
        # and there is at least one failed job, return true, any() returns false
        # if the iterable is empty
        return any(failed_jobs)
