# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from logging import getLogger
from pathlib import Path

from ruamel.yaml import YAML

from openqabot.errors import NoTestIssuesError
from openqabot.types import Data
from openqabot.types.aggregate import Aggregate
from openqabot.types.incidents import Incidents
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
        "Loading meta-data from %s (with incidents: %r, with aggregates: %r)",
        path,
        not incidents,
        not aggregate,
    )
    for p in get_yml_list(path):
        try:
            data = loader.load(p)
        except Exception:  # pylint: disable=broad-except
            log.exception("")
            continue

        try:
            settings = data.get("settings")
        except AttributeError:
            log.warning("The YAML file '%s' contains no valid data for bot settings. Ignoring", p)
            continue

        if "product" not in data:
            log.debug("Skipping invalid config %s", p)
            continue

        if settings:
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
                        log.warning("No 'test_issues' in %s config", data["product"])
                else:
                    continue
    log.debug("Loaded %i incidents/aggregates", len(ret))
    return ret


def read_products(path: Path) -> list[Data]:
    loader = YAML(typ="safe")
    ret = []

    log.debug("Loading products from %s", path)
    for p in get_yml_list(path):
        data = loader.load(p)

        if not data:
            log.info("Skipping invalid config %s - empty config", p)
            continue
        if not isinstance(data, dict):
            log.info("Skipping invalid config %s - invalid format", p)
            continue

        try:
            flavor = data["aggregate"]["FLAVOR"]
            distri = data["settings"]["DISTRI"]
            version = data["settings"]["VERSION"]
            product = data["product"]
        except KeyError as e:
            log.info("Skipping config %s with no %s settings", p, e)
            continue

        ret.extend(Data(0, 0, flavor, arch, distri, version, "", product) for arch in data["aggregate"]["archs"])

    return ret


def get_onearch(path: Path) -> set[str]:
    loader = YAML(typ="safe")

    try:
        data = loader.load(path)
    except Exception:  # pylint: disable=broad-except
        log.exception("")
        return set()

    return set(data)
