# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from logging import getLogger
from operator import itemgetter
from pprint import pformat
from typing import Any, Dict, List, NamedTuple, Sequence

from openqabot.dashboard import get_json, patch, put
from openqabot.errors import NoResultsError
from openqabot.types import Data
from openqabot.types.incident import Incident

log = getLogger("bot.loader.qem")


class IncReq(NamedTuple):
    inc: int
    req: int
    type: str = None
    url: str = None
    scm_info: str = None


class JobAggr(NamedTuple):
    id: int
    aggregate: bool
    withAggregate: bool


class LoaderQemException(Exception):
    pass


class NoIncidentResultsError(NoResultsError):
    def __init__(self, inc: int) -> None:
        super().__init__(
            f"Inc {inc} does not have any job_settings. Consider adding package specific settings to the metadata repository."
        )


class NoAggregateResultsError(NoResultsError):
    def __init__(self, inc: int) -> None:
        super().__init__(f"Inc {inc} does not have any aggregates settings")


def get_incidents(token: Dict[str, str]) -> List[Incident]:
    incidents = get_json("api/incidents", headers=token, verify=True)

    if "error" in incidents:
        raise LoaderQemException(incidents)

    xs = []
    for i in incidents:
        incident = Incident.create(i)
        if incident:
            xs.append(incident)

    return xs


def get_active_incidents(token: Dict[str, str]) -> Sequence[int]:
    data = get_json("api/incidents", headers=token)
    return list({i["number"] for i in data})


def get_incidents_approver(token: Dict[str, str]) -> List[IncReq]:
    incidents = get_json("api/incidents", headers=token)
    return [
        IncReq(
            i["number"],
            i["rr_number"],
            i.get("type", ""),
            i.get("url", ""),
            i.get("scm_info", ""),
        )
        for i in incidents
        if i["inReviewQAM"]
    ]


def get_single_incident(token: Dict[str, str], incident_id: int) -> List[IncReq]:
    incident = get_json("api/incidents/" + incident_id, headers=token)
    return [IncReq(incident["number"], incident["rr_number"])]


def get_incident_settings(inc: int, token: Dict[str, str], *, all_incidents: bool = False) -> List[JobAggr]:
    settings = get_json("api/incident_settings/" + str(inc), headers=token)
    if not settings:
        raise NoIncidentResultsError(inc)

    if not all_incidents:
        rrids = [i["settings"].get("RRID", None) for i in settings]
        rrid = sorted([r for r in rrids if r])
        if rrid:
            rrid = rrid[-1]
            settings = [s for s in settings if s["settings"].get("RRID", rrid) == rrid]

    return [JobAggr(i["id"], aggregate=False, withAggregate=i["withAggregate"]) for i in settings]


def get_incident_settings_data(token: Dict[str, str], number: int) -> Sequence[Data]:
    log.info("Getting settings for %s", number)
    data = get_json("api/incident_settings/" + f"{number}", headers=token)
    if "error" in data:
        log.warning("Incident %s contains error: %s", number, data["error"])
        return []

    return [
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
        for d in data
    ]


def get_incident_results(inc: int, token: Dict[str, str]) -> List[Dict[str, Any]]:
    settings = get_incident_settings(inc, token, all_incidents=False)

    ret = []
    for job_aggr in settings:
        data = get_json("api/jobs/incident/" + f"{job_aggr.id}", headers=token)
        ret += data
        if "error" in data:
            raise ValueError(data["error"])

    return ret


def get_aggregate_settings(inc: int, token: Dict[str, str]) -> List[JobAggr]:
    settings = get_json("api/update_settings/" + str(inc), headers=token)
    if not settings:
        raise NoAggregateResultsError(inc)

    # is string comparsion ... so we need reversed sort
    settings = sorted(settings, key=itemgetter("build"), reverse=True)
    # use all data from day (some jobs have set onetime=True)
    # which causes need to use data from both runs
    last_build = settings[0]["build"][:-2]
    return [JobAggr(i["id"], aggregate=True, withAggregate=False) for i in settings if last_build in i["build"]]


def get_aggregate_settings_data(token: Dict[str, str], data: Data) -> Sequence[Data]:
    url = "api/update_settings" + f"?product={data.product}&arch={data.arch}"
    settings = get_json(url, headers=token)
    if not settings:
        log.info("Product: %s on arch: %s does not have any settings", data.product, data.arch)
        return []

    log.debug("Getting id for %s", pformat(data))

    # use last three schedule
    return [
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
        for s in settings[:3]
    ]


def get_aggregate_results(inc: int, token: Dict[str, str]) -> List[Dict[str, Any]]:
    settings = get_aggregate_settings(inc, token)

    ret = []
    for job_aggr in settings:
        data = get_json("api/jobs/update/" + f"{job_aggr.id}", headers=token)
        ret += data
        if "error" in data:
            raise ValueError(data["error"])

    return ret


def update_incidents(token: Dict[str, str], data: Dict[str, Any], **kwargs: Any) -> int:
    retry = kwargs.get("retry", 0)
    query_params = kwargs.get("params", {})
    while retry >= 0:
        retry -= 1
        try:
            ret = patch("api/incidents", headers=token, params=query_params, json=data)
        except Exception:  # pylint: disable=broad-except
            log.exception("")
            return 1
        if ret.status_code == 200:
            log.info("Smelt/Gitea Incidents updated")
        else:
            log.error(
                "Smelt/Gitea Incidents were not synced to dashboard: error %s",
                ret.status_code,
            )
            error_text = ret.text
            if len(error_text):
                log.error(error_text)
            continue
        return 0
    return 2


def post_job(token: Dict[str, str], data: Dict[str, Any]) -> None:
    try:
        result = put("api/jobs", headers=token, json=data)
        if result.status_code != 200:
            log.error(result.text)

    except Exception:  # pylint: disable=broad-except
        log.exception("")


def update_job(token: Dict[str, str], job_id: int, data: Dict[str, Any]) -> None:
    try:
        result = patch("api/jobs/" + str(job_id), headers=token, json=data)
        if result.status_code != 200:
            log.error(result.text)

    except Exception:  # pylint: disable=broad-except
        log.exception("")
