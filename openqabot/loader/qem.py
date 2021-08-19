from logging import getLogger
from operator import itemgetter
from typing import Dict, List, NamedTuple

import requests

from .. import QEM_DASHBOARD
from ..errors import EmptyChannels, EmptyPackagesError, NoRepoFoundError, NoResultsError
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


def get_aggeregate_settings(inc: int, token: Dict[str, str]) -> List[JobAggr]:
    # TODO: Error handling
    settings = requests.get(
        QEM_DASHBOARD + "api/update_settings/" + str(inc), headers=token
    ).json()
    if not settings:
        raise NoResultsError("Inc %s hasn't any aggregate__settings" % str(inc))

    settings = sorted(settings, key=itemgetter("build"))
    last_build = settings[0]["build"]
    return [JobAggr(i["id"], True, False) for i in settings if i["build"] == last_build]
