# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Sequence
from itertools import chain
from logging import getLogger
from operator import itemgetter
from pprint import pformat
from typing import Any, NamedTuple

import requests

from openqabot.dashboard import get_json, patch, put
from openqabot.errors import NoResultsError
from openqabot.types import Data
from openqabot.types.incident import Incident

log = getLogger("bot.loader.qem")


class IncReq(NamedTuple):
    inc: int
    req: int
    type: str | None = None
    url: str | None = None
    scm_info: str | None = None


class JobAggr(NamedTuple):
    id: int
    aggregate: bool
    with_aggregate: bool


class LoaderQemError(Exception):
    pass


class NoIncidentResultsError(NoResultsError):
    def __init__(self, inc: int) -> None:
        super().__init__(
            # ruff: noqa: E501 line-too-long
            f"Inc {inc} does not have any job_settings. Consider adding package specific settings to the metadata repository."
        )


class NoAggregateResultsError(NoResultsError):
    def __init__(self, inc: int) -> None:
        super().__init__(f"Inc {inc} does not have any aggregates settings")


def get_incidents(token: dict[str, str]) -> list[Incident]:
    incidents = get_json("api/incidents", headers=token, verify=True)

    if "error" in incidents:
        raise LoaderQemError(incidents)

    return [incident for i in incidents if (incident := Incident.create(i))]


def get_active_incidents(token: dict[str, str]) -> Sequence[int]:
    data = get_json("api/incidents", headers=token)
    return list({i["number"] for i in data})


def get_incidents_approver(token: dict[str, str]) -> list[IncReq]:
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


def get_single_incident(token: dict[str, str], incident_id: int) -> list[IncReq]:
    incident = get_json(f"api/incidents/{incident_id}", headers=token)
    return [IncReq(incident["number"], incident["rr_number"])]


def get_incident_settings(inc: int, token: dict[str, str], *, all_incidents: bool = False) -> list[JobAggr]:
    settings = get_json(f"api/incident_settings/{inc}", headers=token)
    if not settings:
        raise NoIncidentResultsError(inc)

    if not all_incidents:
        rrids = [i["settings"].get("RRID", None) for i in settings]
        rrid = sorted([r for r in rrids if r])
        if rrid:
            rrid = rrid[-1]
            settings = [s for s in settings if s["settings"].get("RRID", rrid) == rrid]

    return [JobAggr(i["id"], aggregate=False, with_aggregate=i["withAggregate"]) for i in settings]


def get_incident_settings_data(token: dict[str, str], number: int) -> Sequence[Data]:
    log.info("Fetching settings for incident %s", number)
    data = get_json("api/incident_settings/" + f"{number}", headers=token)
    if "error" in data:
        log.warning("Incident %s error: %s", number, data["error"])
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


def get_incident_results(inc: int, token: dict[str, Any]) -> list[dict[str, Any]]:
    settings = get_incident_settings(inc, token, all_incidents=False)

    def _get_job_data(job_aggr: JobAggr) -> list[dict[str, Any]]:
        data = get_json("api/jobs/incident/" + f"{job_aggr.id}", headers=token)
        if "error" in data:
            raise ValueError(data["error"])
        return data

    all_data = (_get_job_data(job_aggr) for job_aggr in settings)
    return list(chain.from_iterable(all_data))


def get_aggregate_settings(inc: int, token: dict[str, str]) -> list[JobAggr]:
    settings = get_json(f"api/update_settings/{inc}", headers=token)
    if not settings:
        raise NoAggregateResultsError(inc)

    # we need a reverse sort due to doing a string comparison
    settings = sorted(settings, key=itemgetter("build"), reverse=True)
    # use all data from day (some jobs have set onetime=True)
    # which causes need to use data from both runs
    last_build = settings[0]["build"][:-2]
    return [JobAggr(i["id"], aggregate=True, with_aggregate=False) for i in settings if last_build in i["build"]]


def get_aggregate_settings_data(token: dict[str, str], data: Data) -> Sequence[Data]:
    url = "api/update_settings" + f"?product={data.product}&arch={data.arch}"
    settings = get_json(url, headers=token)
    if not settings:
        log.info("No aggregate settings found for product %s on arch %s", data.product, data.arch)
        return []

    log.debug("Resolving aggregate ID for data: %s", pformat(data))

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


def get_aggregate_results(inc: int, token: dict[str, Any]) -> list[dict[str, Any]]:
    settings = get_aggregate_settings(inc, token)

    def _get_job_data(job_aggr: JobAggr) -> list[dict[str, Any]]:
        data = get_json("api/jobs/update/" + f"{job_aggr.id}", headers=token)
        if "error" in data:
            raise ValueError(data["error"])
        return data

    all_data = (_get_job_data(job_aggr) for job_aggr in settings)
    return list(chain.from_iterable(all_data))


def update_incidents(token: dict[str, str], data: dict[str, Any], **kwargs: Any) -> int:
    retry = kwargs.get("retry", 0)
    query_params = kwargs.get("params", {})
    while retry >= 0:
        retry -= 1
        try:
            ret = patch("api/incidents", headers=token, params=query_params, json=data)
        except requests.exceptions.RequestException:
            log.exception("QEM Dashboard API request failed")
            return 1
        if ret.status_code == 200:
            log.info("QEM Dashboard incidents updated successfully")
        else:
            log.error("QEM Dashboard incident sync failed: Status %s", ret.status_code)
            error_text = ret.text
            if len(error_text):
                log.error("QEM Dashboard error response: %s", error_text)
            continue
        return 0
    return 2


def post_job(token: dict[str, str], data: dict[str, Any]) -> None:
    try:
        result = put("api/jobs", headers=token, json=data)
        if result.status_code != 200:
            log.error("Dashboard API error: Could not post job: %s", result.text)

    except requests.exceptions.RequestException:
        log.exception("QEM Dashboard API request failed")


def update_job(token: dict[str, str], job_id: int, data: dict[str, Any]) -> None:
    try:
        result = patch(f"api/jobs/{job_id}", headers=token, json=data)
        if result.status_code != 200:
            log.error("Dashboard API error: Could not update job %s: %s", job_id, result.text)

    except requests.exceptions.RequestException:
        log.exception("QEM Dashboard API request failed")
