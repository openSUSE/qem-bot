# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""OSC request helpers."""

from __future__ import annotations

from functools import cache
from logging import getLogger
from typing import TYPE_CHECKING

import osc.core

from openqabot.config import OBS_GROUP, OBS_URL

if TYPE_CHECKING:
    from argparse import Namespace

log = getLogger("bot.requests")


@cache
def get_obs_request_list(project: str, req_state: tuple) -> list:
    """Get a list of requests from OBS."""
    return osc.core.get_request_list(OBS_URL, project, req_state=req_state)


def find_request_in_project(project: str, relevant_states: list[str]) -> osc.core.Request | None:
    """Find a relevant OBS request within a project."""
    log.debug(
        "Checking for product increment requests to be reviewed by %s on %s",
        OBS_GROUP,
        project,
    )
    obs_requests = get_obs_request_list(project, tuple(relevant_states))
    filtered_requests = (
        request
        for request in sorted(obs_requests, reverse=True)
        for review in request.reviews
        if review.by_group == OBS_GROUP and review.state in relevant_states
    )
    return next(filtered_requests, None)


@cache
def _find_request_on_obs_cached(
    request_id: int | None, *, accepted: bool, build_project: str
) -> osc.core.Request | None:
    """Find product increment requests on OBS with hashable arguments."""
    relevant_states = ["new", "review"]
    if accepted:
        relevant_states.append("accepted")

    if request_id is None:
        relevant_request = find_request_in_project(build_project, relevant_states)
    else:
        log.debug("Checking specified request %i", request_id)
        relevant_request = osc.core.Request.from_api(OBS_URL, request_id)

    if relevant_request is None:
        states_str = "/".join(relevant_states)
        log.info("Skipping approval: %s: No relevant requests in states %s", build_project, states_str)
    else:
        log.info("Found product increment request on %s: %s", build_project, relevant_request.id)
        if hasattr(relevant_request.state, "to_xml"):
            log.debug(relevant_request.to_str())
    return relevant_request


def find_request_on_obs(args: Namespace, build_project: str) -> osc.core.Request | None:
    """Find a relevant product increment request on OBS."""
    return _find_request_on_obs_cached(args.request_id, accepted=args.accepted, build_project=build_project)


find_request_on_obs.cache_clear = _find_request_on_obs_cached.cache_clear  # type: ignore[attr-defined]
