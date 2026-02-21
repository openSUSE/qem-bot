# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""SMELT loader."""

from __future__ import annotations

from concurrent import futures
from logging import getLogger
from typing import Any, cast

import urllib3
import urllib3.exceptions
from jsonschema import ValidationError, validate

from openqabot import config
from openqabot.utils import retry10 as retried_requests
from openqabot.utils import walk

log = getLogger("bot.loader.smelt")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ACTIVE_FST = '{ incidents(status_Name_Iexact:"active", first: 100 ) { pageInfo \
{ hasNextPage endCursor} edges { node { incidentId }}}}'

ACTIVE_NEXT = '{ incidents(status_Name_Iexact:"active", first: 100, \
after: "%(cursor)s" ) { pageInfo { hasNextPage endCursor} edges { node { incidentId}}}}'

INCIDENT = '{incidents(incidentId: %(incident)s) { edges { node {emu project \
repositories { edges { node { name } } } requestSet(kind: "RR") { edges { node \
{ requestId status { name } reviewSet { edges { node { assignedByGroup { name } \
status { name } } } } } } } packages { edges { node { name } } } } } \
    edges{ node { crd priority } } } }'

ACTIVE_INC_SCHEMA = {
    "type": "object",
    "properties": {
        "data": {
            "type": "object",
            "properties": {
                "incidents": {
                    "type": "object",
                    "properties": {
                        "edges": {
                            "type": "array",
                            "items": {
                                "node": {
                                    "type": "object",
                                    "properties": {
                                        "incidentId": {
                                            "type": "number",
                                        },
                                    },
                                    "required": ["incidentId"],
                                },
                            },
                        },
                        "pageInfo": {
                            "type": "object",
                            "properties": {
                                "hasNextPage": {
                                    "type": "boolean",
                                },
                                "endCursor": {
                                    "type": "string",
                                },
                            },
                            "required": ["hasNextPage", "endCursor"],
                        },
                    },
                    "required": ["edges", "pageInfo"],
                },
            },
            "required": ["incidents"],
        },
    },
    "required": ["data"],
}

INCIDENT_SCHEMA = {
    "type": "object",
    "properties": {
        "data": {
            "type": "object",
            "properties": {
                "incidents": {
                    "type": "object",
                    "properties": {
                        "edges": {
                            "type": "array",
                            "items": {
                                "node": {
                                    "type": "object",
                                    "properties": {
                                        "emu": {
                                            "type": "boolean",
                                        },
                                        "project": {
                                            "type": "string",
                                        },
                                        "repositories": {
                                            "type": "object",
                                        },
                                        "packages": {
                                            "type": "object",
                                        },
                                        "requestSet": {
                                            "type": "object",
                                        },
                                        "crd": {
                                            "type": "string",
                                        },
                                        "priority": {
                                            "type": "number",
                                        },
                                    },
                                },
                            },
                        },
                    },
                    "required": ["edges"],
                },
            },
            "required": ["incidents"],
        },
    },
    "required": ["data"],
}


def get_json(query: str, host: str | None = None) -> dict[str, Any]:
    """Fetch JSON data from SMELT using a GraphQL query."""
    host = host or config.settings.smelt_graphql
    return retried_requests.get(host, params={"query": query}, verify=False).json()


def get_active_submission_ids() -> set[int]:
    """Get active incidents from SMELT GraphQL API."""
    active: set[int] = set()

    has_next = True
    cursor = None

    while has_next:
        query = ACTIVE_NEXT % {"cursor": cursor} if cursor else ACTIVE_FST
        ndata = get_json(query)
        try:
            validate(instance=ndata, schema=ACTIVE_INC_SCHEMA)
        except ValidationError:
            log.exception("SMELT API error: Invalid data structure received for active incidents")
            return set()
        incidents = ndata["data"]["incidents"]
        active.update(x["node"]["incidentId"] for x in incidents["edges"])
        has_next = incidents["pageInfo"]["hasNextPage"]
        if has_next:
            cursor = incidents["pageInfo"]["endCursor"]

    log.info("Loaded %s active incidents from SMELT", len(active))

    return active


def get_submission_from_smelt(incident: int) -> dict[str, Any] | None:
    """Fetch detailed information for a single submission from SMELT."""
    query = INCIDENT % {"incident": incident}

    log.info("Fetching details for SMELT incident smelt:%s", incident)
    inc_result = get_json(query)
    try:
        validate(instance=inc_result, schema=INCIDENT_SCHEMA)
        inc_result = cast("dict[str, Any]", walk(inc_result["data"]["incidents"]["edges"][0]["node"]))
    except ValidationError:
        log.exception("SMELT API error: Invalid data for SMELT incident smelt:%s", incident)
        return None
    except Exception:
        log.exception("SMELT API error: Unexpected error for SMELT incident smelt:%s", incident)
        return None

    return inc_result


def get_submissions(active: set[int]) -> list[dict[str, Any]]:
    """Fetch detailed information for a set of submissions from SMELT in parallel."""
    with futures.ThreadPoolExecutor() as executor:
        future_sub = [executor.submit(get_submission_from_smelt, inc) for inc in active]
        submissions = (future.result() for future in futures.as_completed(future_sub))
        return [sub for sub in submissions if sub]
