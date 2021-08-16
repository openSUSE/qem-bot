#!/usr/bin/python3

import sys
from argparse import ArgumentParser
from operator import itemgetter
from typing import List, NamedTuple
from functools import lru_cache

import requests as R

import osc.conf
import osc.core

QEM_DASHBOARD = "http://dashboard.qam.suse.de/api/"
QAM_GROUP = "qam-openqa"


class EmptyError(Exception):
    pass


class IncReq(NamedTuple):
    inc: int
    req: int


class JobAggr(NamedTuple):
    job_id: int
    aggregate: bool
    withAggregate: bool


def get_incidents() -> List[IncReq]:
    # TODO: Error handling
    incidents = R.get(QEM_DASHBOARD + "incidents", headers=TOKEN).json()
    return [IncReq(i["number"], i["rr_number"]) for i in incidents if i["inReviewQAM"]]


def get_incident_settings(inc: int) -> List[JobAggr]:
    settings = R.get(
        QEM_DASHBOARD + "incident_settings/" + str(inc), headers=TOKEN
    ).json()
    if not settings:
        raise EmptyError("Inc %s hasn't any job_settings" % str(inc))
    return [JobAggr(i["id"], False, i["withAggregate"]) for i in settings]


def get_aggeregate_settings(inc: int) -> List[JobAggr]:
    settings = R.get(
        QEM_DASHBOARD + "update_settings/" + str(inc), headers=TOKEN
    ).json()
    if not settings:
        raise EmptyError("Inc %s hasn't any aggregate__settings" % str(inc))

    settings = sorted(settings, key=itemgetter("build"))
    last_build = settings[0]["build"]
    return [JobAggr(i["id"], True, False) for i in settings if i["build"] == last_build]


def get_incident_result(jobs: List[JobAggr], api:str) -> bool:
    res = False
    for job in jobs:
        try:
            res = get_jobs(job, api)
        except EmptyError as e:
            continue
        if not res:
            return res
    return res


@lru_cache(maxsize=128)
def get_jobs(job: JobAggr, api:str) -> bool:
    results = R.get(QEM_DASHBOARD + api + str(job.job_id), headers=TOKEN).json()

    if not results:
        raise EmptyError("Job %s not found " % str(job.job_id))
    
    return any(r["status"] == "passed" for r in results)


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument(
        "-t",
        "--token",
        type=str,
        help="Authorization token for qam-dashboard",
        required=True,
    )
    parser.add_argument(
        "-d", "--dry", action="store_true", help="dry run, dont appove incidents"
    )

    parsed = parser.parse_args(sys.argv[1:])

    global TOKEN
    TOKEN = {"Authorization": f"Token {parsed.token}"}

    incrqs = get_incidents()

    incidents_to_approve = []

    for inc in incrqs:
        try:
            i_jobs = get_incident_settings(inc.inc)
        except EmptyError as e:
            print(e)
            continue
        try:
            u_jobs = get_aggeregate_settings(inc.inc)
        except EmptyError as e:
            print(e)
            if any(i.withAggregate for i in i_jobs):
                print("Aggregate for %s needed" % str(inc.inc))
                continue
            u_jobs = []

        if not get_incident_result(i_jobs, "jobs/incident/"):
            print("Inc %s has failed job in incidents" % str(inc.inc))
            continue
        if any(i.withAggregate for i in i_jobs):
            if not get_incident_result(u_jobs, "jobs/update/"):
                print("Inc %s has failed job in aggregates" % str(inc.inc))
                continue

        # everything is green --> approve inc
        incidents_to_approve.append(inc)

    msg = "Request accepted for 'qam-openqa' by qam-dashboard"
    if not parsed.dry:

        osc.conf.get_config(override_apiurl="https://api.suse.de")

        for rq in incidents_to_approve:
            print(
                "Accepting review for SUSE:Maintenace:%s:%s"
                % (str(rq.inc), str(rq.req))
            )
            try:
                osc.core.change_review_state(
                    apiurl="https://api.suse.de",
                    reqid=str(rq.req),
                    newstate="accepted",
                    by_group="qam-openqa",
                    message=msg
                )
            except Exception as e:
                print(e)
                continue
    else:
        print("Incidents to approve:")
        print(incidents_to_approve)

    sys.exit(0)
