# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Re-apply the recomputed priority to jobs that are still scheduled in openQA."""

from __future__ import annotations

from http import HTTPStatus
from logging import getLogger
from typing import TYPE_CHECKING, Any

import requests

from openqabot import dashboard
from openqabot.config import settings
from openqabot.openqa import OpenQAInterface

if TYPE_CHECKING:
    from .submissions import SubContext

log = getLogger("bot.types.reprioritize")


def _openqa_client() -> OpenQAInterface:
    """Return the openQA client used for reprioritization; a function so tests can patch it."""
    return OpenQAInterface()


def _job_key(stored_settings: dict[str, Any]) -> tuple[str, ...]:
    """Return the settings identifying one job of a scheduled submission.

    openQA returns job settings as text (``REPOHASH`` is ``"42"``) while the
    dashboard stores the integer, so compare the string form of both sides.
    """
    return tuple(str(stored_settings.get(key)) for key in ("FLAVOR", "ARCH", "VERSION", "REPOHASH"))


def _job_target(current: int, stored: int | None, desired: int) -> int:
    """Return the openQA priority preserving openQA's own throttling penalty.

    openQA adds penalties for long-running and resource-heavy jobs
    (``_apply_prio_throttling``) on top of the posted ``_PRIORITY``. The difference between the
    stored job priority and the stored base keeps that penalty intact while applying our delta.
    """
    baseline = settings.default_prio if stored is None else stored
    return desired + current - baseline


def _planned_jobs(
    client: OpenQAInterface, matched: dict[str, Any], stored: int | None, desired: int
) -> list[tuple[int, int, int]] | None:
    """Return the ``(job id, current priority, target priority)`` of the jobs to shift.

    None means openQA could not be queried, so no caller reports a priority as stored that was
    never applied.
    """
    stored_settings = matched.get("settings", {})
    if not (build := stored_settings.get("BUILD")):
        return None
    jobs = client.get_scheduled_jobs_by_build(build)
    if jobs is None:
        return None
    key = _job_key(stored_settings)
    plans = []
    for job in jobs:
        if _job_key(job.get("settings") or {}) != key:
            continue
        if (current := job.get("priority")) is None:
            continue
        if (target := _job_target(current, stored, desired)) != current:
            plans.append((int(job["id"]), current, target))
    return plans


def _restore(client: OpenQAInterface, applied: list[tuple[int, int]]) -> None:
    """Undo already applied priorities so the whole context stays retryable."""
    for job_id, previous in applied:
        if not client.set_priority(job_id, previous):
            log.error("Could not restore priority %s of openQA job %s", previous, job_id)


def _apply(client: OpenQAInterface, plans: list[tuple[int, int, int]]) -> list[tuple[int, int]] | None:
    """Apply the planned priorities, returning the applied ``(job id, previous priority)`` pairs.

    One context is reprioritized as a whole: a failed write restores the jobs already shifted,
    because the dashboard keeps the stale base priority that a later run would otherwise apply a
    second time on top of them.
    """
    applied = []
    for job_id, current, target in plans:
        if client.set_priority(job_id, target):
            applied.append((job_id, current))
            log.info("Reprioritized openQA job %s from %s to %s", job_id, current, target)
            continue
        log.warning("Could not reprioritize openQA job %s, it keeps priority %s", job_id, current)
        _restore(client, applied)
        return None
    return applied


def _store_priority(matched: dict[str, Any], desired: int) -> bool:
    """Persist the applied priority in the dashboard so the next run does not repeat the delta."""
    payload = {key: value for key, value in matched.items() if key != "id"}
    payload["settings"] = {**(matched.get("settings") or {}), "_PRIORITY": desired}
    try:
        res = dashboard.put("api/incident_settings", headers=settings.dashboard_token_dict, json=payload)
    except requests.exceptions.RequestException:
        log.exception("Dashboard update failed: could not store reprioritized settings %s", payload["settings"])
        return False
    if not HTTPStatus.OK <= res.status_code < HTTPStatus.MULTIPLE_CHOICES:
        log.error("Dashboard update failed with status %s: %r", res.status_code, res.text[:200])
        return False
    return True


def scheduled(ctx: SubContext, matched: dict[str, Any], desired: int) -> None:
    """Apply ``desired`` to the still scheduled jobs of an already scheduled context.

    Runs inside the regular scheduling decision, so it must stay best-effort: openQA or dashboard
    failures are logged and leave the context unchanged for the next run. ``matched`` is the empty
    placeholder of a failed dashboard lookup, which skips the context.
    """
    if not matched:
        return
    stored = matched.get("settings", {}).get("_PRIORITY")
    if stored == desired:
        return
    if abs(desired - (settings.default_prio if stored is None else stored)) < settings.min_prio_delta:
        log.debug(
            "Submission %s (%s, %s) prio %s -> %s below min_prio_delta", ctx.sub, ctx.flavor, ctx.arch, stored, desired
        )
        return
    client = _openqa_client()
    if not client:
        log.debug(
            "Not reprioritizing submission %s: openQA instance %s is not the main one", ctx.sub, client.url.netloc
        )
        return
    _apply_planned(client, ctx, matched, stored, desired)


def _apply_planned(
    client: OpenQAInterface, ctx: SubContext, matched: dict[str, Any], stored: int | None, desired: int
) -> None:
    """Shift the planned jobs and converge the dashboard baseline; all or nothing."""
    plans = _planned_jobs(client, matched, stored, desired)
    if plans is None:
        return
    if client.dry:
        for job_id, current, target in plans:
            log.info("Would reprioritize openQA job %s from %s to %s", job_id, current, target)
        return
    applied = _apply(client, plans)
    if applied is None:
        return
    if not _store_priority(matched, desired):
        _restore(client, applied)
        log.warning(
            "Dashboard still stores prio %s of submission %s, restored openQA jobs %s",
            stored,
            ctx.sub,
            [job_id for job_id, _ in applied],
        )
