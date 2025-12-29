# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Iterator
from logging import getLogger
from pathlib import Path

from ruamel.yaml import YAML, YAMLError

from openqabot.errors import NoTestIssuesError
from openqabot.types.aggregate import Aggregate
from openqabot.types.submissions import Submissions
from openqabot.types.types import Data
from openqabot.utils import get_yml_list

log = getLogger("bot.loader.config")


def _try_load(loader: YAML, path: Path) -> dict | None:
    try:
        data = loader.load(path)
    except YAMLError:
        log.exception("YAML load failed: File %s", path)
        return None

    if data is None:
        log.info("Configuration skipped: File %s is empty", path)
        return None

    if not isinstance(data, dict):
        log.info("Configuration skipped: File %s has invalid format", path)
        return None

    return data


def _load_one_metadata(
    path: Path,
    data: dict,
    *,
    aggregate: bool,
    submissions: bool,
    extrasettings: set[str],
) -> Iterator[Aggregate | Submissions]:
    settings = data.get("settings")
    if not settings:
        log.info("Configuration skipped: Missing settings in '%s'", path)
        return

    product = data.get("product")
    if not product:
        log.debug("Configuration skipped: Missing 'product' in '%s'", path)
        return

    product_repo = data.get("product_repo")
    product_version = data.get("product_version")

    for key in data:
        if key == "incidents" and not submissions:
            yield Submissions(product, product_repo, product_version, settings, data["incidents"], extrasettings)
        elif key == "aggregate" and not aggregate:
            try:
                yield Aggregate(product, product_repo, product_version, settings, data["aggregate"])
            except NoTestIssuesError:
                log.info("Aggregate configuration skipped: Missing 'test_issues' for product %s", product)


def load_metadata(
    path: Path,
    *,
    aggregate: bool,
    submissions: bool,
    extrasettings: set[str],
) -> list[Aggregate | Submissions]:
    loader = YAML(typ="safe")
    log.debug("Loading metadata from %s: Submissions=%s, Aggregates=%s", path, not submissions, not aggregate)

    return [
        item
        for p in get_yml_list(path)
        if (data := _try_load(loader, p))
        for item in _load_one_metadata(
            p, data, aggregate=aggregate, submissions=submissions, extrasettings=extrasettings
        )
    ]


def _parse_product(path: Path, data: dict) -> Iterator[Data]:
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
        return

    yield from (Data(0, 0, flavor, arch, distri, version, "", product) for arch in archs)


def read_products(path: Path) -> list[Data]:
    loader = YAML(typ="safe")
    log.debug("Loading product definitions from %s", path)

    return [item for p in get_yml_list(path) if (data := _try_load(loader, p)) for item in _parse_product(p, data)]


def get_onearch(path: Path) -> set[str]:
    loader = YAML(typ="safe")

    try:
        data = loader.load(path)
    except (YAMLError, FileNotFoundError):
        return set()

    return set(data)
