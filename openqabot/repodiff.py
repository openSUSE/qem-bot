# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import gzip
import json
import re
from argparse import Namespace
from collections import defaultdict
from logging import getLogger
from typing import Any, DefaultDict, Dict, List, NamedTuple, Optional, Set, Tuple, Union

from . import OBS_DOWNLOAD_URL
from .utils import retry10 as requests

log = getLogger("bot.repo_diff")
ns = "{http://linux.duke.edu/metadata/common}"
package_tag = ns + "package"
name_tag = ns + "name"
version_tag = ns + "version"
arch_tag = ns + "arch"
primary_re = re.compile(r".*-primary.xml(?:.gz)?$")


try:
    import lxml.etree as ET

    log.info("Using lxml for XML parsing when computing repo diff")
except ImportError:
    import xml.etree.ElementTree as ET

    log.warning("Using built-in XML parsing when computing repo diff")


class Package(NamedTuple):
    name: str
    epoch: str
    version: str
    rel: str
    arch: str


class RepoDiff:
    def __init__(self, args: Optional[Namespace]) -> None:
        self.args = args

    def _make_repodata_url(self, project: str) -> str:
        path = project.replace(":", ":/")
        return f"{OBS_DOWNLOAD_URL}/{path}/repodata/"

    def _find_primary_repodata(self, rows: List[Dict[str, Any]]) -> Optional[str]:
        return next((r["name"] for r in rows if primary_re.search(r.get("name", ""))), None)

    def _request_and_dump(self, url: str, name: str, as_json: bool = False) -> Union[bytes, Dict[str, Any]]:
        log.debug("Requesting %s", url)
        name = "responses/" + name.replace("/", "_")
        if self.args is not None and self.args.fake_data:
            if as_json:
                with open(name, "r", encoding="utf8") as json_file:
                    return json.loads(json_file.read())
            else:
                with open(name, "rb") as binary_file:
                    return binary_file.read()
        resp = requests.get(url)
        if self.args is not None and self.args.dump_data and not self.args.fake_data:
            with open(name, "wb") as output_file:
                output_file.write(resp.content)
        return resp.json() if as_json else resp.content

    def _load_repodata(self, project: str) -> Optional[ET.Element]:
        url = self._make_repodata_url(project)
        repo_data_listing = self._request_and_dump(url + "?jsontable=1", f"repodata-listing-{project}.json", True)
        rows = repo_data_listing.get("data", [])
        repo_data_file = self._find_primary_repodata(rows)
        if repo_data_file is None:
            return None
        repo_data_raw = self._request_and_dump(url + repo_data_file, repo_data_file)
        repo_data = gzip.decompress(repo_data_raw) if repo_data_file.endswith(".gz") else repo_data_raw
        log.debug("Parsing %s", repo_data_file)
        return ET.fromstring(repo_data)

    def _load_packages(self, project: str) -> DefaultDict[str, Set[Package]]:
        repo_data = self._load_repodata(project)
        log.debug("Loading packages for %s", project)
        packages_by_arch = defaultdict(set)
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

    def compute_diff(self, repo_a: str, repo_b: str) -> Tuple[DefaultDict[str, Set[Package]], int]:
        packages_by_arch_a = self._load_packages(repo_a)
        packages_by_arch_b = self._load_packages(repo_b)
        diff_by_arch = defaultdict(set)
        count = 0
        for arch, packages_b in packages_by_arch_b.items():
            packages_a = packages_by_arch_a[arch]
            log.debug("Found %i packages for %s in repo %s", len(packages_a), arch, repo_a)
            log.debug("Found %i packages for %s in repo %s", len(packages_b), arch, repo_b)
            diff = packages_b - packages_a
            count += len(diff)
            diff_by_arch[arch] = diff
        return (diff_by_arch, count)

    def __call__(self) -> int:
        args = self.args
        diff, count = self.compute_diff(args.repo_a, args.repo_b)
        log.debug(
            "Repo %s contains %i packages that are not in repo %s",
            args.repo_b,
            count,
            args.repo_a,
        )
        print(json.dumps(diff, indent=4, default=list))  # noqa: T201
        return len(diff)
