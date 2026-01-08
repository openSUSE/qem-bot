# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from logging import getLogger
from pathlib import Path

from ruamel.yaml import YAML, YAMLError

from openqabot.errors import NoTestIssuesError
from openqabot.types.aggregate import Aggregate
from openqabot.types.incidents import Incidents
from openqabot.types.types import Data
from openqabot.utils import get_yml_list

log = getLogger("bot.loader.config")


def load_metadata(
    path: Path,
    *,
    aggregate: bool,
    incidents: bool,
    extrasettings: set[str],
) -> list[Aggregate | Incidents]:
    ret: list[Aggregate | Incidents] = []

    loader = YAML(typ="safe")

    log.debug(
        "Loading metadata from %s: Incidents=%s, Aggregates=%s",
        path,
        not incidents,
        not aggregate,
    )
    for p in get_yml_list(path):
        try:
            data = loader.load(p)
        except YAMLError:
            log.exception("YAML load failed: File %s", p)
            continue

        try:
            settings = data.get("settings")
        except AttributeError:
            log.info("Configuration skipped: Missing settings in '%s'", p)
            continue

        if "product" not in data:
            log.debug("Configuration skipped: Missing 'product' in '%s'", p)
            continue
        for key in data:
            if key == "incidents" and not incidents:
                ret.append(
                    Incidents(
                        data["product"],
                        data.get("product_repo"),
                        data.get("product_version"),
                        settings,
                        data[key],
                        extrasettings,
                    ),
                )
            elif key == "aggregate" and not aggregate:
                try:
                    ret.append(
                        Aggregate(
                            data["product"],
                            data.get("product_repo"),
                            data.get("product_version"),
                            settings,
                            data[key],
                        ),
                    )
                except NoTestIssuesError:
                    log.info("Aggregate configuration skipped: Missing 'test_issues' for product %s", data["product"])
            else:
                continue
    log.debug("Metadata loaded: %d items", len(ret))
    return ret


def read_products(path: Path) -> list[Data]:
    loader = YAML(typ="safe")
    ret = []

    log.debug("Loading product definitions from %s", path)
    for p in get_yml_list(path):
        data = loader.load(p)

        if not data:
            log.info("Configuration skipped: File %s is empty", p)
            continue
        if not isinstance(data, dict):
            log.info("Configuration skipped: File %s has invalid format", p)
            continue

        try:
            flavor = data["aggregate"]["FLAVOR"]
            distri = data["settings"]["DISTRI"]
            version = data["settings"]["VERSION"]
            product = data["product"]
        except KeyError as e:
            log.info("Configuration skipped: File %s missing required setting %s", p, e)
            continue

        ret.extend(Data(0, 0, flavor, arch, distri, version, "", product) for arch in data["aggregate"]["archs"])

    return ret


def get_onearch(path: Path) -> set[str]:
    loader = YAML(typ="safe")

    try:
        data = loader.load(path)
    except (YAMLError, FileNotFoundError):
        return set()

    return set(data)
