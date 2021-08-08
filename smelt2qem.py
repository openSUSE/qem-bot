#!/usr/bin/python3
from argparse import ArgumentParser
import concurrent.futures as CT
from copy import deepcopy
from operator import itemgetter
import sys
from typing import Set

import requests as R
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SMELT = "https://smelt.suse.de/graphql"
QEM_DASHBOARD = "http://dashboard.qam.suse.de/api"


ACTIVE_FST = '{ incidents(status_Name_Iexact:"active", first: 100 ) { pageInfo \
{ hasNextPage endCursor} edges { node { incidentId }}}}'
ACTIVE_NEXT = '{ incidents(status_Name_Iexact:"active", first: 100, \
after: "%(cursor)s" ) { pageInfo { hasNextPage endCursor} edges { node { incidentId}}}}'

INCIDENT = '{incidents(incidentId: %(incident)s) { edges { node {emu project \
repositories { edges { node { name } } } requestSet(kind: "RR") { edges { node \
{ requestId status { name } reviewSet { edges { node { assignedByGroup { name } \
status { name } } } } } } } packages { edges { node { name } } } } } } }'


def walk(inc):
    if isinstance(inc, list):
        for i, j in enumerate(inc):
            inc[i] = walk(j)
    if isinstance(inc, dict):
        if len(inc) == 1:
            if "edges" in inc:
                return walk(inc["edges"])
            elif "node" in inc:
                tmp = deepcopy(inc["node"])
                del inc["node"]
                inc.update(tmp)
        for key in inc:
            if isinstance(inc[key], (list, dict)):
                inc[key] = walk(inc[key])
    return inc


def get_active_incidents(smelt: str) -> Set[int]:
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
            ndata = R.get(smelt, params={"query": query}, verify=False).json()
        except Exception as e:
            print(e)
            raise e

        active.update(
            x["node"]["incidentId"] for x in ndata["data"]["incidents"]["edges"]
        )
        has_next = ndata["data"]["incidents"]["pageInfo"]["hasNextPage"]
        if has_next:
            cursor = ndata["data"]["incidents"]["pageInfo"]["endCursor"]

    print("Loaded %s active incidents" % len(active))

    return active


def get_incident(smelt: str, incident: int):
    query = INCIDENT % {"incident": incident}

    print("getting info about incident %s" % incident)

    try:
        inc_result = R.get(smelt, params={"query": query}, verify=False).json()
    except Exception as e:
        print(e)
        raise e
    try:
        inc_result = walk(inc_result["data"]["incidents"]["edges"][0]["node"])
    except Exception as e:
        print(incident)
        print(e)
        print(inc_result)
        raise e

    return inc_result


def get_incidents(smelt: str):
    active = get_active_incidents(smelt)

    incidents = []

    with CT.ThreadPoolExecutor() as executor:
        future_inc = [executor.submit(get_incident, smelt, inc) for inc in active]

        for future in CT.as_completed(future_inc):
            incidents.append(future.result())

    return incidents


def rr(requestSet):
    if not requestSet:
        return None
    else:
        rr = sorted(requestSet, key=itemgetter("requestId"), reverse=True)[0]
        if rr["status"]["name"] in ("new", "review", "accepted"):
            return rr
        else:
            return None


def rrv(rr_number):
    if rr_number["reviewSet"]:
        if rr_number["status"]["name"] == "review":
            return True
        else:
            return False
    else:
        return False


def rra(rr_number):
    if (
        rr_number["status"]["name"] == "accepted"
        or rr_number["status"]["name"] == "new"
    ):
        return True
    else:
        return False


def rrqam(rr_number):
    if rr_number["reviewSet"]:
        rr = (r for r in rr_number["reviewSet"] if r["assignedByGroup"])
        review = [r for r in rr if r["assignedByGroup"]["name"] == "qam-openqa"]
        if review and review[0]["status"]["name"] in ("review", "new"):
            return True
    return False


def create_record(inc):

    incident = {}
    incident["isActive"] = True
    rr_number = rr(inc["requestSet"])
    if rr_number:
        inReview = rrv(rr_number)
        approved = rra(rr_number)
        inReviewQAM = rrqam(rr_number)
        rr_number = rr_number["requestId"]
    else:
        inReview = False
        approved = False
        inReviewQAM = False

    if approved:
        incident["isActive"] = False

    incident["project"] = inc["project"]
    incident["number"] = int(inc["project"].split(":")[-1])
    incident["emu"] = inc["emu"]
    incident["packages"] = [package["name"] for package in inc["packages"]]
    incident["channels"] = [repo["name"] for repo in inc["repositories"]]
    incident["inReview"] = inReview
    incident["approved"] = approved
    incident["rr_number"] = rr_number
    incident["inReviewQAM"] = inReviewQAM
    return incident


def create_list(incidents):
    return [create_record(inc) for inc in incidents]


if __name__ == "__main__":

    parser = ArgumentParser()
    parser.add_argument("token", type=str)

    parsed = parser.parse_args(sys.argv[1:])
    TOKEN = {"Authorization": f"Token {parsed.token}"}

    a = get_incidents(SMELT)
    data = create_list(a)
    incidents = "%s/incidents"
    result = R.patch(incidents % QEM_DASHBOARD, headers=TOKEN, json=data)
    test = R.get(incidents % QEM_DASHBOARD, headers=TOKEN)
    print(test.json())
    print(result)
