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
from lxml import etree  # ty: ignore[unresolved-import]

from openqabot.errors import NoResultsError

from .utils import get_obs_filter_params
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
    """Information about a package."""

    name: str
    epoch: str
    version: str
    rel: str
    arch: str


class RepoDiff:
    """Repository diff computation."""

    def __init__(self, args: Namespace | None) -> None:
        """Initialize the RepoDiff class."""
        self.args = args

    def make_repodata_url(self, url: str) -> str:  # noqa: PLR6301
        """Construct the URL for repository metadata."""
        return f"{url.rstrip('/')}/repodata/"

    def find_primary_repodata(self, rows: list[dict[str, Any]]) -> str | None:  # noqa: PLR6301
        """Find the primary XML metadata file in a list of repository files."""
        return next((r["name"] for r in rows if primary_re.search(r.get("name", ""))), None)

    @staticmethod
    def decompress(repo_data_file: str, repo_data_raw: bytes) -> bytes:
        """Decompress repository metadata if it is compressed."""
        if repo_data_file.endswith(".gz"):
            return gzip.decompress(repo_data_raw)
        if repo_data_file.endswith(".zst"):
            return pyzstd.decompress(repo_data_raw)
        return repo_data_raw

    @staticmethod
    def _fetch_or_read_bytes(
        url: str, filepath: str, *, fake_data: bool, dump_data: bool, params: dict[str, Any] | None
    ) -> bytes | None:

        if fake_data:
            return Path(filepath).read_bytes()

        resp = retried_requests.get(url, params=params)
        if not resp.ok:
            log.info("Failed to fetch data from %s: %s %s", url, resp.status_code, resp.reason)
            return None

        if dump_data:
            Path(filepath).write_bytes(resp.content)

        return resp.content

    def request_and_dump(
        self,
        url: str,
        name: str,
        *,
        as_json: bool = False,
        params: dict[str, Any] | None = None,
    ) -> bytes | dict[str, Any] | None:
        """Fetch data from a URL and optionally dump it to a file for fake data usage."""
        log.debug("Fetching repository data from %s", url)
        filepath = "tests/fixtures/responses/" + name.replace("/", "_")

        fake_data = self.args is not None and getattr(self.args, "fake_data", False)
        dump_data = self.args is not None and getattr(self.args, "dump_data", False)
        source = filepath if fake_data else url

        try:
            content = self._fetch_or_read_bytes(url, filepath, fake_data=fake_data, dump_data=dump_data, params=params)
        except (FileNotFoundError, PermissionError):
            log.info("Failed to read %s: File not found", source)
            return None
        except Exception:
            log.exception("Failed to fetch or dump data from %s", source)
            return None

        if content is None:
            return None

        if not as_json:
            return content

        try:
            return json.loads(content)
        except (json.JSONDecodeError, requests.exceptions.JSONDecodeError):
            log.info("Failed to parse %s", source)
            return None

    def get_staged_update_name(self, repo_url: str) -> str:
        """Get the name of the staged update package from a repository URL."""
        packages_by_arch = self.load_packages(repo_url)
        packages = set().union(*packages_by_arch.values())
        if len(packages) == 0:
            error_msg = "No packages detected"
            raise NoResultsError(error_msg)
        return min(packages, key=lambda p: p.name).name

    def load_repodata(self, url: str) -> etree.Element | None:
        """Load and parse repository primary metadata for a repository URL."""
        repodata_url = self.make_repodata_url(url)
        repo_data_listing = self.request_and_dump(
            repodata_url,
            f"repodata-listing-{url.replace('/', '_').replace(':', '_')}.json",
            as_json=True,
            params=get_obs_filter_params(r".*-primary\.xml.*"),
        )
        if not repo_data_listing or not isinstance(repo_data_listing, dict):
            log.error("Could not load repo data for URL %s", url)
            return None

        rows = repo_data_listing.get("data", [])
        repo_data_file = self.find_primary_repodata(rows)
        if repo_data_file is None:
            log.warning("Repository metadata not found: Primary repodata missing in %s", repodata_url)
            return None
        repo_data_raw = self.request_and_dump(repodata_url + repo_data_file, repo_data_file)
        if not isinstance(repo_data_raw, bytes):
            return None
        repo_data = RepoDiff.decompress(repo_data_file, repo_data_raw)
        log.debug("Parsing repository metadata file: %s", repo_data_file)
        return etree.fromstring(repo_data)

    def load_packages(self, url: str) -> defaultdict[str, set[Package]]:
        """Load the list of packages from a repository URL."""
        repo_data = self.load_repodata(url)
        packages_by_arch = defaultdict(set)
        if repo_data is None or not hasattr(repo_data, "iterfind"):
            log.error("Could not load repo data for URL %s", url)
            return packages_by_arch
        log.debug("Loading package list for repository %s", url)
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
        """Compute the difference between two sets of packages grouped by architecture."""
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
        """Compute the package diff between two repositories."""
        try:
            packages_by_arch_a = self.load_packages(repo_a)
            packages_by_arch_b = self.load_packages(repo_b)
            return RepoDiff.compute_diff_for_packages(repo_a, packages_by_arch_a, repo_b, packages_by_arch_b)
        except Exception:
            log.exception("Repo diff computation failed for repositories %s and %s", repo_a, repo_b)
            return defaultdict(set), 0

    def __call__(self) -> int:
        """Run the repository diff computation."""
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
