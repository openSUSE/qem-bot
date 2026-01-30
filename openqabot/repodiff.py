# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Repository diff computation."""

from __future__ import annotations

import gzip
import json
import re
import sys
from collections import defaultdict
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import pyzstd
import requests
from lxml import etree  # type: ignore[unresolved-import]

from .config import OBS_DOWNLOAD_URL
from .utils import retry10 as retried_requests

if TYPE_CHECKING:
    from argparse import Namespace

log = getLogger("bot.repo_diff")
ns = "{http://linux.duke.edu/metadata/common}"
package_tag = ns + "package"
name_tag = ns + "name"
version_tag = ns + "version"
arch_tag = ns + "arch"
primary_re = re.compile(r".*-primary.xml(?:.(gz|zst))?$")


class Package(NamedTuple):
    name: str
    epoch: str
    version: str
    rel: str
    arch: str


class RepoDiff:
    def __init__(self, args: Namespace | None) -> None:
        """Initialize the RepoDiff class."""
        self.args = args

    def make_repodata_url(self, project: str) -> str:  # noqa: PLR6301
        path = project.replace(":", ":/")
        return f"{OBS_DOWNLOAD_URL}/{path}/repodata/"

    def find_primary_repodata(self, rows: list[dict[str, Any]]) -> str | None:  # noqa: PLR6301
        return next((r["name"] for r in rows if primary_re.search(r.get("name", ""))), None)

    @staticmethod
    def decompress(repo_data_file: str, repo_data_raw: bytes) -> bytes:
        if repo_data_file.endswith(".gz"):
            return gzip.decompress(repo_data_raw)
        if repo_data_file.endswith(".zst"):
            return pyzstd.decompress(repo_data_raw)
        return repo_data_raw

    def request_and_dump(self, url: str, name: str, *, as_json: bool = False) -> bytes | dict[str, Any] | None:
        log.debug("Fetching repository data from %s", url)
        name = "responses/" + name.replace("/", "_")
        try:
            if self.args is not None and self.args.fake_data:
                if as_json:
                    return json.loads(Path(name).read_text(encoding="utf8"))
                return Path(name).read_bytes()
            resp = retried_requests.get(url)
            if self.args is not None and self.args.dump_data and not self.args.fake_data:
                Path(name).write_bytes(resp.content)
            return resp.json() if as_json else resp.content
        except (FileNotFoundError, PermissionError):
            log.exception("Failed to read %s", name)
        except (json.JSONDecodeError, requests.exceptions.JSONDecodeError):
            log.exception("Failed to parse %s", name)
        except Exception:
            log.exception("Failed to fetch or dump data from %s", url)
        return None

    def load_repodata(self, project: str) -> etree.Element | None:
        url = self.make_repodata_url(project)
        repo_data_listing = self.request_and_dump(
            url + "?jsontable=1",
            f"repodata-listing-{project}.json",
            as_json=True,
        )
        if not repo_data_listing or not isinstance(repo_data_listing, dict):
            log.error("Could not load repo data for project %s", project)
            return None

        rows = repo_data_listing.get("data", [])
        repo_data_file = self.find_primary_repodata(rows)
        if repo_data_file is None:
            log.warning("Repository metadata not found: Primary repodata missing in %s", url)
            return None
        repo_data_raw = self.request_and_dump(url + repo_data_file, repo_data_file)
        if not isinstance(repo_data_raw, bytes):
            return None
        repo_data = RepoDiff.decompress(repo_data_file, repo_data_raw)
        log.debug("Parsing repository metadata file: %s", repo_data_file)
        return etree.fromstring(repo_data)

    def load_packages(self, project: str) -> defaultdict[str, set[Package]]:
        repo_data = self.load_repodata(project)
        packages_by_arch = defaultdict(set)
        if repo_data is None or not hasattr(repo_data, "iterfind"):
            log.error("Could not load repo data for project %s", project)
            return packages_by_arch
        log.debug("Loading package list for project %s", project)
        for package in repo_data.iterfind(package_tag):
            if package.get("type") != "rpm":
                continue
            name = package.find(name_tag).text
            version_info = package.find(version_tag)
            epoch = version_info.get("epoch", "0")
            version = version_info.get("ver", "0")
            rel = version_info.get("rel", "0")
            arch = package.find(arch_tag).text
            packages_by_arch[arch].add(Package(name, epoch, version, rel, arch))
        return packages_by_arch

    @staticmethod
    def compute_diff_for_packages(
        repo_a: str,
        packages_by_arch_a: defaultdict[str, set[Package]],
        repo_b: str,
        packages_by_arch_b: defaultdict[str, set[Package]],
    ) -> tuple[defaultdict[str, set[Package]], int]:
        diff_by_arch = defaultdict(set)
        count = 0
        for arch, packages_b in packages_by_arch_b.items():
            packages_a = packages_by_arch_a[arch]
            log.debug("Found %d packages for architecture %s in repository %s", len(packages_a), arch, repo_a)
            log.debug("Found %d packages for architecture %s in repository %s", len(packages_b), arch, repo_b)
            diff = packages_b - packages_a
            count += len(diff)
            diff_by_arch[arch] = diff
        return (diff_by_arch, count)

    def compute_diff(self, repo_a: str, repo_b: str) -> tuple[defaultdict[str, set[Package]], int]:
        try:
            packages_by_arch_a = self.load_packages(repo_a)
            packages_by_arch_b = self.load_packages(repo_b)
            return RepoDiff.compute_diff_for_packages(repo_a, packages_by_arch_a, repo_b, packages_by_arch_b)
        except Exception:
            log.exception("Repo diff computation failed for projects %s and %s", repo_a, repo_b)
            return defaultdict(set), 0

    def __call__(self) -> int:
        args = self.args
        if args is None:
            log.error("RepoDiff called without arguments")
            return 1
        try:
            diff, count = self.compute_diff(args.repo_a, args.repo_b)
        except FileNotFoundError as e:
            log.critical("Failed to load fake data: %s (use --dump-data to generate it)", e)
            raise SystemExit from None
        log.debug(
            "Repository %s has %d new packages compared to %s",
            args.repo_b,
            count,
            args.repo_a,
        )
        sys.stdout.write(json.dumps(diff, indent=4, default=list) + "\n")
        return len(diff)
