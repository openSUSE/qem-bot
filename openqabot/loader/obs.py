# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""OBS project introspection: build results, multibuild flavors and productcompose.

Emits the channels and packages a submission builds; knows nothing about a forge.
"""

from __future__ import annotations

import re
import urllib.error
from dataclasses import dataclass, field
from logging import getLogger
from typing import TYPE_CHECKING, Any, cast

import osc.core
import osc.util.xml
from osc.connection import http_GET
from osc.core import MultibuildFlavorResolver

from openqabot import config
from openqabot.loader.fixtures import read_utf8, read_xml
from openqabot.loader.productcompose import (
    ARCHS,
    get_productcompose_packages_per_arch,
    productcompose_package,
    safe_fake_project,
)
from openqabot.loader.repourl import repo_listing, split_repo_dir_name
from openqabot.types.channels.slfo import get_product_name, get_product_name_and_version_from_scmsync
from openqabot.types.submission_key import SubmissionKey

if TYPE_CHECKING:
    from lxml import etree  # ty: ignore[unresolved-import]

log = getLogger("bot.loader.obs")


@dataclass
class BuildResults:
    """Results of a build."""

    projects: set[str] = field(default_factory=set)
    successful: set[str] = field(default_factory=set)
    unpublished: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    unavailable: set[str] = field(default_factory=set)


OBS_PROJECT_SHOW_REGEX = re.compile(r".*/project/show/([^/\s\?\#\)]+)")


def get_product_version_from_repo_listing(project: str, product_name: str, repository: str) -> str:
    """Determine the product version by inspecting an OBS repository listing."""
    names = repo_listing(project, repository) or ()
    versions = (split_repo_dir_name(name)[1] for name in names if name.startswith(f"{product_name}-"))
    return next(filter(None, versions), "")


def _get_product_version(res: etree._Element, project: str, product_name: str) -> str:
    """Extract product version from scmsync element or repository listing."""
    # read product version from scmsync element if possible, e.g. 15.99
    scmsync_versions = (get_product_name_and_version_from_scmsync(e.text)[1] for e in res.findall("scmsync") if e.text)
    if product_version := next(filter(None, scmsync_versions), ""):
        return product_version

    # read product version from directory listing if the project is for a concrete product
    if product_name and config.settings.is_obs_product_enabled(product_name):
        return get_product_version_from_repo_listing(project, product_name, res.get("repository"))
    return ""


def add_channel_for_build_result(
    project: str,
    arch: str,
    product_name: str,
    res: etree._Element,
    projects: set[str],
) -> str:
    """Construct a channel string for a build result and add it to the project set."""
    channel = f"{project}:{arch}"
    if arch == "local":
        return channel

    product_version = _get_product_version(res, project, product_name)

    # append product version to channel if known; otherwise skip channel if this is for a concrete product
    if product_version:
        channel = f"{channel}#{product_version}"
    elif product_name:
        log.debug("Channel skipped: Product version for build result %s:%s could not be determined", project, arch)
        return channel

    projects.add(channel)
    return channel


def _update_scminfo(submission: dict[str, Any], res: etree._Element, project: str, product: str) -> None:
    """Update SCM info in the submission dict."""
    scm_key = f"scminfo_{product}" if product else "scminfo"
    for e in res.findall("scminfo"):
        found = e.text
        if found:
            existing = submission.get(scm_key)
            if existing and found != existing:
                msg = "PR %s: Inconsistent SCM info for project %s: found '%s' vs '%s'"
                log.warning(msg, SubmissionKey.from_submission_dict(submission), project, found, existing)
                continue
            submission[scm_key] = found


def _update_build_statuses(res: etree._Element, results: BuildResults) -> None:
    """Update successful and failed packages based on build status."""
    statuses = res.findall("status")
    results.successful.update(s.get("package") for s in statuses if s.get("code") == "succeeded")
    results.failed.update(s.get("package") for s in statuses if s.get("code") not in {"excluded", "succeeded"})


def add_build_result(
    submission: dict[str, Any],
    res: etree._Element,
    results: BuildResults,
) -> None:
    """Process a single build result and update submission and results."""
    project = res.get("project")
    product = get_product_name(project)

    _update_scminfo(submission, res, project, product)

    channel = add_channel_for_build_result(project, res.get("arch"), product, res, results.projects)

    if not config.settings.is_obs_product_enabled(product):
        return

    if res.get("state") != "published":
        results.unpublished.add(channel)
        return

    _update_build_statuses(res, results)


def get_multibuild_data(obs_project: str) -> str:
    """Fetch the multibuild configuration data of a project's productcompose package."""
    r = MultibuildFlavorResolver(config.settings.obs_url, obs_project, productcompose_package(obs_project))
    return cast("str", r.get_multibuild_data())


def _filter_archs_by_packages(
    relevant_archs: set[str],
    packages: list[str],
    packages_per_arch: dict[str, frozenset[str]],
    obs_project: str,
) -> set[str]:
    known_pkgs = set().union(*packages_per_arch.values())
    relevant_packages = frozenset(packages) & known_pkgs
    supported = {arch for arch in relevant_archs if relevant_packages <= packages_per_arch.get(arch, frozenset())}
    if not supported:
        log.warning(
            "No arch for %s supports all PR packages %s, keeping %s unfiltered",
            obs_project,
            sorted(relevant_packages),
            sorted(relevant_archs),
        )
        return relevant_archs
    if dropped := relevant_archs - supported:
        log.info(
            "Skipping archs %s for %s: packages %s are listed for other architectures",
            sorted(dropped),
            obs_project,
            sorted(relevant_packages),
        )
    return supported


def _load_multibuild_data(obs_project: str, *, fake_data: bool) -> str | None:
    if not safe_fake_project(obs_project, fake_data=fake_data):
        return None
    try:
        return read_utf8(f"_multibuild-124-{obs_project}.xml") if fake_data else get_multibuild_data(obs_project)
    except OSError as e:
        log.warning("Could not determine relevant architectures for %s: %s", obs_project, e)
        return None


def determine_relevant_archs(
    obs_project: str,
    *,
    packages: list[str] | None = None,
    fake_data: bool,
) -> set[str] | None:
    """Determine the relevant architectures of an OBS project from its multibuild flavors and productcompose.

    The `_multibuild` file of `000productcompose` is read and every architecture from `ARCHS` that
    a flavor name ends with is considered relevant.

    Build results may list archs (e.g. `local` or `ppc64le`) as published even though no repos exist
    for them. Considering those would cause problems later on (e.g. when computing the repohash), so
    only the archs found in the flavors are kept.

    When `packages` are given, an architecture is dropped if the productcompose lists one of them for
    another architecture only. When no remaining architecture supports every package, e.g. because a
    PR touches packages of different architectures, all architectures are kept instead of none.

    Returns:
        The set of relevant architectures, or None if the multibuild data could not be retrieved.

    """
    if (multibuild_data := _load_multibuild_data(obs_project, fake_data=fake_data)) is None:
        return None
    flavors = MultibuildFlavorResolver.parse_multibuild_data(multibuild_data)
    relevant_archs = {arch for flavor in flavors for arch in ARCHS if flavor.endswith(arch)}
    if packages and (packages_per_arch := get_productcompose_packages_per_arch(obs_project, fake_data=fake_data)):
        relevant_archs = _filter_archs_by_packages(relevant_archs, packages, packages_per_arch, obs_project)
    log.debug("Relevant archs for %s: %s", obs_project, sorted(relevant_archs))
    return relevant_archs


def is_build_result_relevant(res: etree._Element, relevant_archs: set[str] | None) -> bool:
    """Check if a build result is relevant for the current product and architecture."""
    if config.settings.obs_repo_type and res.get("repository") != config.settings.obs_repo_type:
        log.debug(
            "Build result %s ignored. Expected obs_repo_type='%s' does not match with actual '%s' from repo",
            res.get("project"),
            config.settings.obs_repo_type,
            res.get("repository"),
        )
        return False
    arch = res.get("arch")
    return arch == "local" or relevant_archs is None or arch in relevant_archs


def _get_project_results(obs_project: str, *, fake_data: bool, results: BuildResults) -> list[etree._Element]:
    """Fetch build results for an OBS project."""
    build_info_url = osc.core.makeurl(config.settings.obs_url, ["build", obs_project, "_result"])
    if fake_data:
        return read_xml("build-results-124-" + obs_project).getroot().findall("result")
    try:
        return osc.util.xml.xml_parse(http_GET(build_info_url)).getroot().findall("result")
    except urllib.error.HTTPError:
        results.unavailable.add(obs_project)
        log.info("Build results for project %s unreadable, skipping: %s", obs_project, build_info_url)
        return []


def _process_obs_url(
    url: str,
    submission: dict[str, Any],
    *,
    fake_data: bool,
    results: BuildResults,
) -> None:
    """Process an OBS URL and update submission build results."""
    if not (project_match := OBS_PROJECT_SHOW_REGEX.search(url)):
        return
    obs_project = project_match.group(1)
    log.debug("Checking OBS project %s", obs_project)
    relevant_archs = determine_relevant_archs(obs_project, packages=submission["packages"], fake_data=fake_data)

    for res in _get_project_results(obs_project, fake_data=fake_data, results=results):
        if is_build_result_relevant(res, relevant_archs):
            add_build_result(submission, res, results)


def add_build_results(submission: dict[str, Any], obs_urls: list[str], *, fake_data: bool) -> None:
    """Aggregate build results from multiple OBS URLs into a submission."""
    results = BuildResults()

    for url in obs_urls:
        _process_obs_url(url, submission, fake_data=fake_data, results=results)

    if results.unpublished:
        log.info(
            "PR %s: Some repos not published yet: %s",
            SubmissionKey.from_submission_dict(submission),
            ", ".join(results.unpublished),
        )
    if results.failed:
        log.info(
            "PR %s: Some packages failed: %s", SubmissionKey.from_submission_dict(submission), ", ".join(results.failed)
        )

    submission.update({
        "failed_or_unpublished_packages": sorted(results.failed | results.unpublished | results.unavailable),
        "successful_packages": sorted(results.successful),
    })

    channels = submission.setdefault("channels", [])
    channels.extend(result for result in sorted(results.projects) if result not in channels)

    if not submission.get("scminfo") and (
        len(config.settings.obs_products_set),
        "all" in config.settings.obs_products_set,
    ) == (1, False):
        submission["scminfo"] = submission.get("scminfo_" + next(iter(config.settings.obs_products_set)), "")
