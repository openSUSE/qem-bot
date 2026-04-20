# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Source report loader."""

from __future__ import annotations

import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from logging import getLogger
from typing import Any
from urllib.error import HTTPError

import osc.core
from lxml import etree  # ty: ignore[unresolved-import]

from openqabot import config
from openqabot.repodiff import Package, RepoDiff
from openqabot.types.types import OBSBinary

log = getLogger("bot.loader.sourcereport")


def parse_source_report(
    binary: OBSBinary,
    source_report: str,
    packages: defaultdict[str, set[Package]],
) -> None:
    """Fetch and parse a single source report XML file from OBS.

    Downloads the specified source report from the Build Service, parses the XML
    content to identify all binary packages associated with the source package,
    and updates the provided 'packages' dictionary. Packages are added to both
    their specific architecture and the 'noarch' category.

    Args:
        binary: The OBS coordinates (project, package, repo, arch) for the report.
        source_report: The filename of the source report to be processed.
        packages: The target dictionary to store discovered packages, grouped by arch.

    """
    log.debug("Processing source report %s for %s", source_report, binary)
    with tempfile.TemporaryDirectory() as tmpdirname:
        source_report_xml_path = f"{tmpdirname}/source-report-{binary.project}-{binary.repo}-{binary.arch}.xml"
        osc.core.get_binary_file(
            config.settings.obs_url,
            prj=binary.project,
            package=binary.package,
            repo=binary.repo,
            arch=binary.arch,
            filename=source_report,
            target_filename=source_report_xml_path,
        )
        source_report_xml = etree.parse(source_report_xml_path)
    source_report_root = source_report_xml.getroot()
    for b in source_report_root.iterfind("binary"):
        binary_arch = b.get("arch")
        packages[binary_arch].add(Package(b.get("name"), "", b.get("version"), b.get("release"), binary_arch))
        packages["noarch"].add(Package(b.get("package"), "", "", "", "noarch"))


@lru_cache(maxsize=128)
def get_repos_of_project(prj: str) -> list[Any]:
    """Cache OBS repository lookups for a project."""
    return list(osc.core.get_repos_of_project(config.settings.obs_url, prj=prj))


def find_source_reports(project: str, package: str) -> list[str]:
    """Find source reports for a package in a project."""
    repos = get_repos_of_project(project)
    binaries = [
        osc.core.get_binarylist(config.settings.obs_url, prj=project, repo=repo.name, arch=repo.arch, package=package)
        for repo in repos
    ]
    return [b for binary_list in binaries for b in binary_list if b and b.endswith("Source.report")]


def load_packages_from_source_report(
    action: Any,  # noqa: ANN401
    binary: OBSBinary,
    packages: defaultdict[str, set[Package]],
) -> None:
    """Add packages from source reports of a project to the packages dictionary."""
    log.debug(
        "Finding source reports for package %s in project %s for repo/arch %s/%s",
        action.src_package,
        binary.project,
        binary.repo,
        binary.arch,
    )
    try:
        source_reports = find_source_reports(binary.project, action.src_package)
        for source_report in source_reports:
            parse_source_report(binary, source_report, packages)
    except HTTPError as e:
        log.warning("Failed to add packages from source report: %s", e)


def compute_packages_of_request_from_source_report(
    request: osc.core.Request,
) -> tuple[defaultdict[str, set[Package]], int]:
    """Compute the package diff of a request based on source reports."""
    # target projects (e.g. `SUSE:Products:SLE-Product-SLES:16.0:aarch64`)
    repo_a: defaultdict[str, set[Package]] = defaultdict(set)
    # source projects (e.g. `SUSE:SLFO:Products:SLES:16.0:TEST`)
    repo_b: defaultdict[str, set[Package]] = defaultdict(set)

    def worker(action: Any, binary: OBSBinary) -> defaultdict[str, set[Package]]:  # noqa: ANN401
        packages: defaultdict[str, set[Package]] = defaultdict(set)
        load_packages_from_source_report(action, binary, packages)
        return packages

    tasks = [
        *((a, OBSBinary(a.tgt_project, a.src_package, "images", "local")) for a in request.actions),
        *((a, OBSBinary(a.src_project, a.src_package, "product", "local")) for a in request.actions),
    ]

    with ThreadPoolExecutor() as executor:
        # Use executor.map to ensure exceptions are raised if they occur in threads
        results = list(executor.map(lambda p: worker(*p), tasks))

    # results contains first all "target" projects, then all "source" projects
    num_actions = len(request.actions)
    for i, res in enumerate(results):
        target_repo = repo_a if i < num_actions else repo_b
        for arch, pks in res.items():
            target_repo[arch].update(pks)

    return RepoDiff.compute_diff_for_packages("product repo", repo_a, "TEST repo", repo_b)
