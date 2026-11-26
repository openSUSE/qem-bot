# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Build results of the PR project that a product subproject belongs to."""

from __future__ import annotations

import re
from functools import lru_cache
from logging import getLogger

import osc.core
import osc.util.xml
from osc.connection import http_GET

from openqabot import config
from openqabot.loader.fixtures import read_xml
from openqabot.loader.productcompose import safe_fake_project

# Build status codes of an arch that does not build a package at all. `disabled` belongs here even
# though gitea counts it as a failure, because the PR project disabled that package for the arch.
EXCLUDED_STATUS_CODES = frozenset({"excluded", "disabled"})
PARENT_PROJECT_REGEX = re.compile(r"(.*:PullRequest:\d+):.+")

log = getLogger("bot.loader.parentbuild")


def get_parent_project(obs_project: str) -> str | None:
    """Return the PR project of a product subproject.

    `SUSE:SLFO:1.2:PullRequest:10985:SLES` resolves to `SUSE:SLFO:1.2:PullRequest:10985`. A project that
    is not a product subproject, e.g. the PR project itself, resolves to None: only the subprojects are
    scheduled per product.
    """
    match = PARENT_PROJECT_REGEX.fullmatch(obs_project)
    return match.group(1) if match else None


@lru_cache(maxsize=128)
def get_parent_statuses(parent_project: str, *, fake_data: bool) -> frozenset[tuple[str, str, str]] | None:
    """Read the build statuses of a parent PR project as (arch, package, code) triples."""
    if not safe_fake_project(parent_project, fake_data=fake_data):
        return None
    url = osc.core.makeurl(config.settings.obs_url, ["build", parent_project, "_result"])
    try:
        results = (
            read_xml("build-results-124-" + parent_project).getroot().findall("result")
            if fake_data
            else osc.util.xml.xml_parse(http_GET(url)).getroot().findall("result")
        )
    except (OSError, SyntaxError):
        log.warning("Parent build results of %s unreadable, cannot drop archs: %s", parent_project, url)
        return None
    return frozenset(
        (res.get("arch", ""), status.get("package", ""), status.get("code", ""))
        for res in results
        for status in res.findall("status")
    )


def _filter_archs_by_parent_status(
    relevant_archs: set[str],
    packages: list[str],
    parent_project: str,
    statuses: frozenset[tuple[str, str, str]],
) -> set[str]:
    """Drop archs where the parent PR project excludes all of the given packages."""
    wanted = frozenset(packages)
    per_arch: dict[str, dict[str, set[str]]] = {}
    for arch, pkg, code in statuses:
        if pkg in wanted:
            per_arch.setdefault(arch, {}).setdefault(pkg, set()).add(code)
    decided = {arch: codes for arch, codes in per_arch.items() if set(codes) >= wanted}
    excluded = {arch for arch, codes in decided.items() if all(c <= EXCLUDED_STATUS_CODES for c in codes.values())}
    if undecided := relevant_archs - set(decided):
        log.warning(
            "Parent build results of %s do not report every package %s on archs %s, keeping them",
            parent_project,
            sorted(wanted),
            sorted(undecided),
        )
    if excluded:
        if not (supported := relevant_archs - excluded):
            log.warning(
                "Parent build results of %s exclude packages %s on every arch, keeping %s",
                parent_project,
                sorted(wanted),
                sorted(relevant_archs),
            )
            return relevant_archs
        log.info(
            "Skipping archs %s for %s: packages %s are excluded in the parent project",
            sorted(relevant_archs & excluded),
            parent_project,
            sorted(wanted),
        )
        return supported
    return relevant_archs


def filter_archs_by_parent_results(
    relevant_archs: set[str],
    packages: list[str],
    obs_project: str,
    *,
    fake_data: bool,
) -> set[str]:
    """Drop archs where the parent PR project excludes every package, keeping all on undecidable results."""
    if not packages or not (parent_project := get_parent_project(obs_project)):
        return relevant_archs
    if (statuses := get_parent_statuses(parent_project, fake_data=fake_data)) is None:
        return relevant_archs
    return _filter_archs_by_parent_status(relevant_archs, packages, parent_project, statuses)
