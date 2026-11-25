# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Product compose data of OBS projects."""

from __future__ import annotations

import re
from logging import getLogger

import osc.core
import yaml
from osc.connection import http_GET

from openqabot import config
from openqabot.loader.fixtures import read_utf8

ARCHS = {"x86_64", "aarch64", "ppc64le", "s390x"}
SAFE_PROJECT_REGEX = re.compile(r"[A-Za-z0-9_:.+-]+")

log = getLogger("bot.loader.productcompose")


def safe_fake_project(obs_project: str, *, fake_data: bool) -> bool:
    """Reject project names that could escape the fake data fixture directory."""
    if not fake_data:
        return True
    if SAFE_PROJECT_REGEX.fullmatch(obs_project):
        return True
    log.warning("Invalid project name %s", obs_project)
    return False


def get_productcompose_contents(obs_project: str) -> list[str]:
    """Fetch the contents of every productcompose file of an OBS project."""
    file_list = osc.core.meta_get_filelist(config.settings.obs_url, obs_project, "000productcompose", expand=True)
    pc_files = sorted(f for f in file_list if f.endswith(".productcompose"))
    if len(pc_files) > 1:
        log.info("Merging productcompose files of %s: %s", obs_project, pc_files)
    contents = []
    for pc_file in pc_files:
        url = osc.core.makeurl(config.settings.obs_url, ["source", obs_project, "000productcompose", pc_file])
        contents.append(http_GET(url).read().decode("utf-8"))
    return contents


def _group_archs(name: str, architectures: object) -> set[str]:
    """Architectures of a packageset, preferring its explicit `architectures` key over its name."""
    if isinstance(architectures, list):
        return {arch for arch in architectures if isinstance(arch, str)} & ARCHS
    return {arch for arch in ARCHS if re.search(rf"(^|_){arch}(_|$)", name)}


def _group_arch_packages(group: object) -> tuple[set[str], set[str]] | None:
    if not isinstance(group, dict):
        log.warning("Malformed group in productcompose: %s", type(group))
        return None
    if not isinstance(name := group.get("name"), str):
        log.warning("Malformed group in productcompose without a name: %s", list(group))
        return None
    if not (pkgs := group.get("packages")):
        log.debug("Group %s in productcompose lists no packages", name)
        return None
    if not isinstance(pkgs, list):
        log.warning("Malformed packages in group %s of productcompose: %s", name, type(pkgs))
        return None
    return _group_archs(name, group.get("architectures")), {p for p in pkgs if isinstance(p, str)}


def _parse_productcompose_groups(groups: list[object]) -> dict[str, frozenset[str]]:
    res: dict[str, set[str]] = {}
    for g in groups:
        if entry := _group_arch_packages(g):
            archs, pkgs = entry
            for a in archs:
                res.setdefault(a, set()).update(pkgs)
    return {a: frozenset(p) for a, p in res.items()}


def _parse_productcompose(content: str, obs_project: str) -> dict[str, frozenset[str]] | None:
    """Parse one productcompose document into a mapping of architectures to supported packages."""
    try:
        data = yaml.load(content, Loader=yaml.CSafeLoader)
    except yaml.YAMLError as e:
        log.warning("Could not parse productcompose YAML for %s: %s", obs_project, e)
        return None

    if not isinstance(data, dict):
        log.warning("Malformed productcompose document for %s: %s", obs_project, type(data))
        return None
    groups = data.get("packagesets") or []
    if not isinstance(groups, list):
        log.warning("Malformed packagesets in productcompose of %s: %s", obs_project, type(groups))
        return None
    if per_arch := _parse_productcompose_groups(groups):
        return per_arch
    log.info("No arch-specific packagesets in productcompose of %s", obs_project)
    return None


def _merge_productcompose_archs(contents: list[str], obs_project: str) -> dict[str, frozenset[str]] | None:
    """Merge the architectures of all documents, or None when one of them is unusable."""
    merged: dict[str, set[str]] = {}
    for content in contents:
        if not (per_arch := _parse_productcompose(content, obs_project)):
            return None
        for arch, pkgs in per_arch.items():
            merged.setdefault(arch, set()).update(pkgs)
    return {arch: frozenset(pkgs) for arch, pkgs in merged.items()}


def get_productcompose_packages_per_arch(obs_project: str, *, fake_data: bool) -> dict[str, frozenset[str]] | None:
    """Fetch and parse the productcompose YAML mapping architectures to sets of supported packages.

    All productcompose files of the package are merged, so the result does not depend on the order
    the OBS file list returns them in.
    """
    if not safe_fake_project(obs_project, fake_data=fake_data):
        return None
    try:
        contents = (
            [read_utf8(f"productcompose-124-{obs_project}.yaml")]
            if fake_data
            else get_productcompose_contents(obs_project)
        )
    except OSError as e:
        log.warning("Could not fetch productcompose for %s: %s", obs_project, e)
        return None

    if not contents:
        log.info("No productcompose file for %s, not filtering architectures", obs_project)
        return None
    if not (res := _merge_productcompose_archs(contents, obs_project)):
        return None
    log.debug("Productcompose archs for %s: %s", obs_project, sorted(res))
    return res
