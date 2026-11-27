# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""openQA priority derivation shared by submissions, aggregates and product increments."""

from __future__ import annotations

from functools import lru_cache
from logging import getLogger
from typing import TYPE_CHECKING

import requests

from openqabot import config
from openqabot.errors import LoaderQemError
from openqabot.loader.qem import get_submissions

if TYPE_CHECKING:
    from collections.abc import Sequence

    from openqabot.repodiff import Package
    from openqabot.types.increment import BuildInfo
    from openqabot.types.submission import Submission
    from openqabot.types.types import Repos

log = getLogger("bot.priority")


def openqa_priority(offset: int, scale: int, priority: int) -> int:
    """Map a submission priority to the openQA priority band anchored at ``offset``."""
    return offset - priority // scale


def _version_matches(channel_version: str, build_version: str) -> bool:
    """Return True when two version strings denote the same product version.

    Channel versions drop suffixes in some code streams, e.g. ``12`` for ``12-SP5``
    and ``16`` for ``16.0``, so compare both directions with a separator. Sibling
    streams like ``15-SP4-LTSS`` also match, which is acceptable for a hint.
    """
    return any(
        a == b or a.startswith((f"{b}-", f"{b}."))
        for a, b in ((channel_version, build_version), (build_version, channel_version))
    )


def _channel_version(repo: Repos) -> str:
    """Version of a channel, which SLFO channels carry in ``product_version`` instead of ``version``."""
    return repo.product_version or repo.version


@lru_cache
def dashboard_submissions() -> list[Submission] | None:
    """Submissions from the dashboard for priority lookups, ``None`` when it is unavailable.

    Deriving a priority is best-effort and must never block a scheduling or approval run.
    """
    try:
        return get_submissions()
    except (LoaderQemError, requests.exceptions.RequestException, ValueError, KeyError) as e:
        log.warning("Could not load submissions for priority derivation: %s", e)
        return None


def max_included_priority(submissions: Sequence[Submission], packages: list[str], version: str) -> int:
    """Highest priority of the not yet released submissions shipping one of ``packages`` for ``version``."""
    return max(
        (
            priority
            for sub in submissions
            if (priority := sub.priority) is not None
            and sub.is_active
            and sub.contains_package(packages)
            and any(_version_matches(_channel_version(repo), version) for repo in sub.channels)
        ),
        default=0,
    )


def increment_priority(build_info: BuildInfo, changed_packages: set[Package]) -> str:
    """Derive the openQA priority of a product increment, the band anchor when the dashboard is unavailable."""
    max_priority = max_included_priority(
        dashboard_submissions() or [], [package.name for package in changed_packages], build_info.version
    )
    priority = openqa_priority(config.settings.pi_priority_offset, config.settings.pi_priority_scale, max_priority)
    log.info(
        "Product increment %s: openQA priority %s from maximum included update priority %s",
        build_info,
        priority,
        max_priority,
    )
    return str(priority)
