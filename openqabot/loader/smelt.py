# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import concurrent.futures as CT
from logging import getLogger
from typing import Any, Dict, List, Optional, Set

import urllib3
import urllib3.exceptions
from jsonschema import ValidationError, validate

from openqabot import SMELT
from openqabot.utils import retry10 as requests
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


def get_json(query: str, host: str = SMELT) -> Dict[str, Any]:
    try:
        return requests.get(host, params={"query": query}, verify=False).json()
    except Exception as e:
        log.exception(e)
        raise


def get_active_incidents() -> Set[int]:
    """Get active incidents from SMELT GraphQL api."""
    active: Set[int] = set()

    has_next = True
    cursor = None

    while has_next:
        query = ACTIVE_NEXT % {"cursor": cursor} if cursor else ACTIVE_FST
        ndata = get_json(query)
        try:
            validate(instance=ndata, schema=ACTIVE_INC_SCHEMA)
        except ValidationError:
            log.exception("Invalid data from SMELT received")
            return set()
        incidents = ndata["data"]["incidents"]
        active.update(x["node"]["incidentId"] for x in incidents["edges"])
        has_next = incidents["pageInfo"]["hasNextPage"]
        if has_next:
            cursor = incidents["pageInfo"]["endCursor"]

    log.info("Loaded %s active incidents", len(active))

    return active


def get_incident(incident: int) -> Optional[Dict[str, Any]]:
    query = INCIDENT % {"incident": incident}

    log.info("Getting info about incident %s from SMELT", incident)
    inc_result = get_json(query)
    try:
        validate(instance=inc_result, schema=INCIDENT_SCHEMA)
        inc_result = walk(inc_result["data"]["incidents"]["edges"][0]["node"])
    except ValidationError:
        log.exception("Invalid data from SMELT for incident %s", incident)
        return None
    except Exception as e:  # pylint: disable=broad-except
        log.exception("Unknown error for incident %s", incident)
        log.exception(e)
        return None

    return inc_result


def get_incidents(active: Set[int]) -> List[Dict[str, Any]]:
    with CT.ThreadPoolExecutor() as executor:
        future_inc = [executor.submit(get_incident, inc) for inc in active]
        incidents = (future.result() for future in CT.as_completed(future_inc))
        return [inc for inc in incidents if inc]
