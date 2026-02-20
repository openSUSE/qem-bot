# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Build info loader."""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING, Any, Callable

from openqabot.types.increment import BuildInfo
from openqabot.utils import retry10 as retried_requests

if TYPE_CHECKING:
    import re

    from openqabot.loader.incrementconfig import IncrementConfig

log = getLogger("bot.loader.buildinfo")
default_flavor = "Online"


def load_build_info(
    config: IncrementConfig,
    build_regex: str,
    product_regex: str,
    version_regex: str,
    get_regex_match: Callable[[str, str], re.Match | None],
) -> set[BuildInfo]:
    """Determine build information from the project's repository listing."""
    build_project_url = config.build_project_url()
    sub_path = config.build_listing_sub_path
    url = f"{build_project_url}/{sub_path}/?jsontable=1"
    log.debug("Checking for '%s' files on %s", build_regex, url)
    rows = retried_requests.get(url).json().get("data", [])

    def get_build_info_from_row(row: dict[str, Any]) -> BuildInfo | None:
        name = row.get("name", "")
        log.debug("Found file: %s", name)
        m = get_regex_match(build_regex, name)
        if not m:
            return None

        product = m.group("product")
        if not get_regex_match(product_regex, product):
            return None

        version = m.group("version")
        if not get_regex_match(version_regex, version):
            log.info("Skipping version string '%s' not matching version regex '%s'", version, version_regex)
            return None
        arch = m.group("arch")
        build = m.group("build")
        try:
            flavor = m.group("flavor")
        except IndexError:
            flavor = default_flavor
        flavor = f"{flavor}-{config.flavor_suffix}"

        if config.flavor in {"any", flavor} and config.version in {"any", version}:
            return BuildInfo(config.distri, product, version, flavor, arch, build)
        return None

    return {build_info for row in rows if (build_info := get_build_info_from_row(row))}
