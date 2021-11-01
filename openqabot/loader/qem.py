from logging import getLogger
from operator import itemgetter
from pprint import pformat
from typing import Dict, List, NamedTuple, Sequence

import requests

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

logger = getLogger("bot.loader.qem")


class IncReq(NamedTuple):
    inc: int
    req: int


class JobAggr(NamedTuple):
    job_id: int
    aggregate: bool
    withAggregate: bool


def get_incidents(token: Dict[str, str]) -> List[Incident]:
    incidents = requests.get(QEM_DASHBOARD + "api/incidents", headers=token).json()

    xs = []
    for i in incidents:
        try:
            xs.append(Incident(i))
        except NoRepoFoundError as e:
            logger.info(
                "Project %s can't calculate repohash %s .. skipping" % (i["project"], e)
            )
        except EmptyChannels as e:
            logger.info("Project %s has empty channels" % i["project"])
        except EmptyPackagesError as e:
            logger.info("Project %s has empty packages" % i["project"])

    return xs


def get_active_incidents(token: Dict[str, str]) -> Sequence[int]:
    try:
        data = requests.get(QEM_DASHBOARD + "api/incidents", headers=token).json()
    except Exception as e:
        logger.exception(e)
        raise e
    return list(set([i["number"] for i in data]))


def get_incidents_approver(token: Dict[str, str]) -> List[IncReq]:
    # TODO: Error handling
    incidents = requests.get(QEM_DASHBOARD + "api/incidents", headers=token).json()
    return [IncReq(i["number"], i["rr_number"]) for i in incidents if i["inReviewQAM"]]


def get_incident_settings(inc: int, token: Dict[str, str]) -> List[JobAggr]:
    # TODO: Error handling.
    settings = requests.get(
        QEM_DASHBOARD + "api/incident_settings/" + str(inc), headers=token
    ).json()
    if not settings:
        raise NoResultsError("Inc %s hasn't any job_settings" % str(inc))
    return [JobAggr(i["id"], False, i["withAggregate"]) for i in settings]


def get_incident_settings_data(token: Dict[str, str], number: int) -> Sequence[Data]:
    url = QEM_DASHBOARD + "api/incident_settings/" + f"{number}"
    logger.info("Getting settings for %s" % number)
    try:
        data = requests.get(url, headers=token).json()
    except Exception as e:
        logger.exception(e)
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


def get_aggeregate_settings(inc: int, token: Dict[str, str]) -> List[JobAggr]:
    # TODO: Error handling
    settings = requests.get(
        QEM_DASHBOARD + "api/update_settings/" + str(inc), headers=token
    ).json()
    if not settings:
        raise NoResultsError("Inc %s hasn't any aggregate__settings" % str(inc))

    # is string comparsion ... so we need reversed sort
    settings = sorted(settings, key=itemgetter("build"), reverse=True)
    # use all data from day (some jobs have set onetime=True)
    # which causes need to use data from both runs
    last_build = settings[0]["build"][:-2]
    return [JobAggr(i["id"], True, False) for i in settings if last_build in i["build"]]


def get_aggeregate_settings_data(token: Dict[str, str], data: Data):
    url = (
        QEM_DASHBOARD
        + "api/update_settings"
        + f"?product={data.product}&arch={data.arch}"
    )
    try:
        settings = requests.get(url, headers=token).json()
    except Exception as e:
        logger.exception(e)
        raise e

    ret = []
    if not settings:
        raise EmptySettings(
            f"Product: {data.product} on arch: {data.arch} hasn't any settings"
        )

    logger.debug("Getting id for %s" % pformat(data))

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


def update_incidents(token: Dict[str, str], data, **kwargs) -> None:
    retry = kwargs["retry"] or 0
    while retry >= 0:
        retry -= 1
        try:
            ret = requests.patch(
                QEM_DASHBOARD + "api/incidents", headers=token, json=data
            )
        except Exception as e:
            logger.exception(e)
            return 1
        else:
            if ret.status_code == 200:
                logger.info("Smelt Incidents updated")
            else:
                logger.error(
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
            logger.error(result.text)

    # TODO: proper error handling ..
    except Exception as e:
        logger.exception(e)
