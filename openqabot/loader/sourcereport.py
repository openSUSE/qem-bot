# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Source report loader."""

from __future__ import annotations

import tempfile
from collections import defaultdict
from logging import getLogger
from typing import Any

import osc.core
from lxml import etree  # type: ignore[unresolved-import]

from openqabot.config import OBS_URL
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
            OBS_URL,
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


def find_source_reports(project: str, package: str) -> list[str]:
    """Find source reports for a package in a project."""
    repos = osc.core.get_repos_of_project(OBS_URL, prj=project)
    binaries = [
        osc.core.get_binarylist(OBS_URL, prj=project, repo=repo.name, arch=repo.arch, package=package) for repo in repos
    ]
    return [b for binary_list in binaries for b in binary_list if b.endswith("Source.report")]


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
    source_reports = find_source_reports(binary.project, action.src_package)
    for source_report in source_reports:
        parse_source_report(binary, source_report, packages)


def compute_packages_of_request_from_source_report(
    request: osc.core.Request,
) -> tuple[defaultdict[str, set[Package]], int]:
    """Compute the package diff of a request based on source reports."""
    repo_a: defaultdict[str, set[Package]] = defaultdict(set)
    repo_b: defaultdict[str, set[Package]] = defaultdict(set)
    for action in request.actions:
        log.debug("Checking action '%s' -> '%s' of request %s", action.src_project, action.tgt_project, request.id)
        # add packages for target project (e.g. `SUSE:Products:SLE-Product-SLES:16.0:aarch64`), that is repo "A"
        load_packages_from_source_report(
            action, OBSBinary(action.tgt_project, action.src_package, "images", "local"), repo_a
        )
        # add packages for source project (e.g. `SUSE:SLFO:Products:SLES:16.0:TEST`), that is repo "B"
        load_packages_from_source_report(
            action, OBSBinary(action.src_project, action.src_package, "product", "local"), repo_b
        )
    return RepoDiff.compute_diff_for_packages("product repo", repo_a, "TEST repo", repo_b)
