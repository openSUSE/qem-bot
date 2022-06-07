# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import concurrent.futures as CT
from logging import getLogger
from typing import Any, List, Set

import requests
import urllib3

from .. import SMELT
from ..utils import walk

logger = getLogger("bot.loader.smelt")


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ACTIVE_FST = '{ incidents(status_Name_Iexact:"active", first: 100 ) { pageInfo \
{ hasNextPage endCursor} edges { node { incidentId }}}}'

ACTIVE_NEXT = '{ incidents(status_Name_Iexact:"active", first: 100, \
after: "%(cursor)s" ) { pageInfo { hasNextPage endCursor} edges { node { incidentId}}}}'

INCIDENT = '{incidents(incidentId: %(incident)s) { edges { node {emu project \
repositories { edges { node { name } } } requestSet(kind: "RR") { edges { node \
{ requestId status { name } reviewSet { edges { node { assignedByGroup { name } \
status { name } } } } } } } packages { edges { node { name } } } } } } }'


def get_active_incidents() -> Set[int]:
    """Get active incidents from SMELT GraphQL api"""

    active: Set[int] = set()

    has_next = True
    cursor = None

    while has_next:
        if cursor:
            query = ACTIVE_NEXT % {"cursor": cursor}
        else:
            query = ACTIVE_FST

        try:
            ndata = requests.get(SMELT, params={"query": query}, verify=False).json()
        except Exception as e:
            logger.exception(e)
            raise e

        active.update(
            x["node"]["incidentId"] for x in ndata["data"]["incidents"]["edges"]
        )
        has_next = ndata["data"]["incidents"]["pageInfo"]["hasNextPage"]
        if has_next:
            cursor = ndata["data"]["incidents"]["pageInfo"]["endCursor"]

    logger.info("Loaded %s active incidents" % len(active))

    return active


def get_incident(incident: int):
    query = INCIDENT % {"incident": incident}

    logger.info("Getting info about incident %s from SMELT" % incident)

    try:
        inc_result = requests.get(SMELT, params={"query": query}, verify=False).json()
    except Exception as e:
        logger.exception(e)
        raise e
    try:
        inc_result = walk(inc_result["data"]["incidents"]["edges"][0]["node"])
    except Exception as e:
        logger.error("Incident %s without valid data from SMELT" % incident)
        logger.exception(e)
        return None

    return inc_result


def get_incidents(active: Set[int]) -> List[Any]:

    incidents = []

    with CT.ThreadPoolExecutor() as executor:
        future_inc = [executor.submit(get_incident, inc) for inc in active]

        for future in CT.as_completed(future_inc):
            incidents.append(future.result())

    incidents = [inc for inc in incidents if inc]
    return incidents
