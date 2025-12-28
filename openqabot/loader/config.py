# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from logging import getLogger
from pathlib import Path

from ruamel.yaml import YAML, YAMLError

from openqabot.errors import NoTestIssuesError
from openqabot.types import Data
from openqabot.types.aggregate import Aggregate
from openqabot.types.incidents import Incidents
from openqabot.utils import get_yml_list

log = getLogger("bot.loader.config")


def _load_one_metadata(
    path: Path,
    data: dict,
    *,
    aggregate: bool,
    incidents: bool,
    extrasettings: set[str],
) -> list[Aggregate | Incidents]:
    ret: list[Aggregate | Incidents] = []
    settings = data.get("settings")
    if not settings:
        log.info("Configuration skipped: Missing settings in '%s'", path)
        return ret

    product = data.get("product")
    if not product:
        log.debug("Configuration skipped: Missing 'product' in '%s'", path)
        return ret

    product_repo = data.get("product_repo")
    product_version = data.get("product_version")

    for key in data:
        if key == "incidents" and not incidents:
            ret.append(Incidents(product, product_repo, product_version, settings, data["incidents"], extrasettings))
        elif key == "aggregate" and not aggregate:
            try:
                ret.append(Aggregate(product, product_repo, product_version, settings, data["aggregate"]))
            except NoTestIssuesError:
                log.info("Aggregate configuration skipped: Missing 'test_issues' for product %s", product)

    return ret


def load_metadata(
    path: Path,
    *,
    aggregate: bool,
    incidents: bool,
    extrasettings: set[str],
) -> list[Aggregate | Incidents]:
    ret: list[Aggregate | Incidents] = []
    loader = YAML(typ="safe")

    log.debug("Loading metadata from %s: Incidents=%s, Aggregates=%s", path, not incidents, not aggregate)
    for p in get_yml_list(path):
        try:
            data = loader.load(p)
        except YAMLError:
            log.exception("YAML load failed: File %s", p)
            continue

        if not isinstance(data, dict):
            continue

        ret.extend(_load_one_metadata(p, data, aggregate=aggregate, incidents=incidents, extrasettings=extrasettings))

    log.debug("Metadata loaded: %d items", len(ret))
    return ret


def _parse_product(path: Path, data: dict) -> list[Data]:
    try:
        aggregate = data["aggregate"]
        flavor = aggregate["FLAVOR"]
        archs = aggregate["archs"]
        settings = data["settings"]
        distri = settings["DISTRI"]
        version = settings["VERSION"]
        product = data["product"]
    except KeyError as e:
        log.info("Configuration skipped: File %s missing required setting %s", path, e)
        return []

    return [Data(0, 0, flavor, arch, distri, version, "", product) for arch in archs]


def read_products(path: Path) -> list[Data]:
    loader = YAML(typ="safe")
    ret: list[Data] = []

    log.debug("Loading product definitions from %s", path)
    for p in get_yml_list(path):
        try:
            data = loader.load(p)
        except YAMLError:
            log.exception("YAML load failed: File %s", p)
            continue

        if not data:
            log.info("Configuration skipped: File %s is empty", p)
            continue
        if not isinstance(data, dict):
            log.info("Configuration skipped: File %s has invalid format", p)
            continue

        ret.extend(_parse_product(p, data))

    return ret


def get_onearch(path: Path) -> set[str]:
    loader = YAML(typ="safe")

    try:
        data = loader.load(path)
    except (YAMLError, FileNotFoundError):
        return set()

    return set(data)
