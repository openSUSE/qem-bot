# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from logging import getLogger
from operator import itemgetter
from pprint import pformat
from typing import Dict, List, NamedTuple, Sequence

import requests as req

from .. import QEM_DASHBOARD
from ..errors import (
    EmptyChannels,
    EmptyPackagesError,
    EmptySettings,
    NoRepoFoundError,
    NoResultsError,
)
from ..types import Data
from ..types.incident import Incident
from ..utils import retry5 as requests

log = getLogger("bot.loader.qem")


class IncReq(NamedTuple):
    inc: int
    req: int


class JobAggr(NamedTuple):
    id: int
    aggregate: bool
    withAggregate: bool


def get_incidents(token: Dict[str, str]) -> List[Incident]:
    incidents = requests.get(QEM_DASHBOARD + "api/incidents", headers=token).json()

    xs = []
    for i in incidents:
        try:
            xs.append(Incident(i))
        except NoRepoFoundError as e:
            log.info(
                "Project %s can't calculate repohash %s .. skipping" % (i["project"], e)
            )
        except EmptyChannels as e:
            log.info(
                "Project %s has empty channels - check incident in SMELT" % i["project"]
            )
        except EmptyPackagesError as e:
            log.info(
                "Project %s has empty packages - check incident in SMELT" % i["project"]
            )

    return xs


def get_active_incidents(token: Dict[str, str]) -> Sequence[int]:
    try:
        data = requests.get(QEM_DASHBOARD + "api/incidents", headers=token).json()
    except Exception as e:
        log.exception(e)
        raise e
    return list(set([i["number"] for i in data]))


def get_incidents_approver(token: Dict[str, str]) -> List[IncReq]:
    incidents = requests.get(QEM_DASHBOARD + "api/incidents", headers=token).json()
    return [IncReq(i["number"], i["rr_number"]) for i in incidents if i["inReviewQAM"]]


def get_single_incident(token: Dict[str, str], id: int) -> List[IncReq]:
    incident = requests.get(QEM_DASHBOARD + "api/incidents/" + id, headers=token).json()
    return [IncReq(incident["number"], incident["rr_number"])]


def get_incident_settings(
    inc: int, token: Dict[str, str], all_incidents: bool = False
) -> List[JobAggr]:
    settings = requests.get(
        QEM_DASHBOARD + "api/incident_settings/" + str(inc), headers=token
    ).json()
    if not settings:
        raise NoResultsError("Inc %s does not have any job_settings" % str(inc))

    if not all_incidents:
        rrids = [i["settings"].get("RRID", None) for i in settings]
        rrid = sorted([r for r in rrids if r])
        if rrid:
            rrid = rrid[-1]
            settings = [s for s in settings if s["settings"].get("RRID", rrid) == rrid]

    return [JobAggr(i["id"], False, i["withAggregate"]) for i in settings]


def get_incident_settings_data(token: Dict[str, str], number: int) -> Sequence[Data]:
    url = QEM_DASHBOARD + "api/incident_settings/" + f"{number}"
    log.info("Getting settings for %s" % number)
    try:
        data = requests.get(url, headers=token).json()
    except Exception as e:
        log.exception(e)
        raise e

    if "error" in data:
        raise ValueError

    ret = []
    for d in data:
        ret.append(
            Data(
                number,
                d["id"],
                d["flavor"],
                d["arch"],
                d["settings"]["DISTRI"],
                d["version"],
                d["settings"]["BUILD"],
                "",
            )
        )

    return ret


def get_incident_results(inc: int, token: Dict[str, str]):
    try:
        settings = get_incident_settings(inc, token)
    except NoResultsError as e:
        raise e

    ret = []
    for job_aggr in settings:
        try:
            data = requests.get(
                QEM_DASHBOARD + "api/jobs/incident/" + f"{job_aggr.id}", headers=token
            ).json()
            ret += data
        except Exception as e:
            log.exception(e)
            raise e
        if "error" in data:
            raise ValueError(data["error"])

    return ret


def get_aggregate_settings(inc: int, token: Dict[str, str]) -> List[JobAggr]:
    settings = requests.get(
        QEM_DASHBOARD + "api/update_settings/" + str(inc), headers=token
    ).json()
    if not settings:
        raise NoResultsError("Inc %s does not have any aggregates settings" % str(inc))

    # is string comparsion ... so we need reversed sort
    settings = sorted(settings, key=itemgetter("build"), reverse=True)
    # use all data from day (some jobs have set onetime=True)
    # which causes need to use data from both runs
    last_build = settings[0]["build"][:-2]
    return [JobAggr(i["id"], True, False) for i in settings if last_build in i["build"]]


def get_aggregate_settings_data(token: Dict[str, str], data: Data):
    url = (
        QEM_DASHBOARD
        + "api/update_settings"
        + f"?product={data.product}&arch={data.arch}"
    )
    try:
        settings = requests.get(url, headers=token).json()
    except Exception as e:
        log.exception(e)
        raise e

    ret = []
    if not settings:
        raise EmptySettings(
            f"Product: {data.product} on arch: {data.arch} does not have any settings"
        )

    log.debug("Getting id for %s" % pformat(data))

    # use last three schedule
    for s in settings[:3]:
        ret.append(
            Data(
                0,
                s["id"],
                data.flavor,
                data.arch,
                data.distri,
                data.version,
                s["build"],
                data.product,
            )
        )

    return ret


def get_aggregate_results(inc: int, token: Dict[str, str]):
    try:
        settings = get_aggregate_settings(inc, token)
    except NoResultsError as e:
        raise e

    ret = []
    for job_aggr in settings:
        try:
            data = requests.get(
                QEM_DASHBOARD + "api/jobs/update/" + f"{job_aggr.id}", headers=token
            ).json()
        except Exception as e:
            log.exception(e)
            raise e
        if "error" in data:
            raise ValueError(data["error"])

        ret += data

    return ret


def update_incidents(token: Dict[str, str], data, **kwargs) -> int:

    retry = kwargs.get("retry", 0)
    while retry >= 0:

        retry -= 1
        try:
            ret = req.patch(QEM_DASHBOARD + "api/incidents", headers=token, json=data)
        except Exception as e:
            log.exception(e)
            return 1
        else:
            if ret.status_code == 200:
                log.info("Smelt Incidents updated")
            else:
                log.error(
                    "Smelt Incidents were not synced to dashboard: error %s"
                    % ret.status_code
                )
                continue
        return 0
    return 2


def post_job(token: Dict[str, str], data) -> None:
    try:
        result = requests.put(QEM_DASHBOARD + "api/jobs", headers=token, json=data)
        if result.status_code != 200:
            log.error(result.text)

    except Exception as e:
        log.exception(e)
