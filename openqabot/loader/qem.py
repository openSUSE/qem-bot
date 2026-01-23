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

from openqabot.config import DEFAULT_SUBMISSION_TYPE
from openqabot.dashboard import get_json, patch, put
from openqabot.errors import NoResultsError
from openqabot.types.submission import Submission
from openqabot.types.types import Data

log = getLogger("bot.loader.qem")


class SubReq(NamedTuple):
    sub: int
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


class NoSubmissionResultsError(NoResultsError):
    def __init__(self, sub: int) -> None:
        super().__init__(
            # ruff: noqa: E501 line-too-long
            f"Submission {sub} does not have any job_settings. Consider adding package specific settings to the metadata repository."
        )


class NoAggregateResultsError(NoResultsError):
    def __init__(self, sub: int) -> None:
        super().__init__(f"Submission {sub} does not have any aggregate settings")


def get_submissions(token: dict[str, str]) -> list[Submission]:
    submissions = get_json("api/incidents", headers=token, verify=True)

    if "error" in submissions:
        raise LoaderQemError(submissions)

    return [submission for s in submissions if (submission := Submission.create(s))]


def get_active_submissions(token: dict[str, str], submission_type: str | None = None) -> Sequence[int]:
    params = {}
    if submission_type:
        params["type"] = submission_type
    data = get_json("api/incidents", headers=token, params=params)
    return list({i["number"] for i in data})


def get_submissions_approver(token: dict[str, str]) -> list[SubReq]:
    submissions = get_json("api/incidents", headers=token)
    return [
        SubReq(
            i["number"],
            i["rr_number"],
            i.get("type", ""),
            i.get("url", ""),
            i.get("scm_info", ""),
        )
        for i in submissions
        if i["inReviewQAM"]
    ]


def get_single_submission(
    token: dict[str, str], submission_id: int, submission_type: str | None = None
) -> list[SubReq]:
    params = {}
    if submission_type:
        params["type"] = submission_type
    submission = get_json(f"api/incidents/{submission_id}", headers=token, params=params)
    return [SubReq(submission["number"], submission["rr_number"], submission.get("type"))]


def get_submission_settings(
    sub: int, token: dict[str, str], *, all_submissions: bool = False, submission_type: str | None = None
) -> list[JobAggr]:
    params = {}
    if submission_type:
        params["type"] = submission_type
    settings = get_json(f"api/incident_settings/{sub}", headers=token, params=params)
    if not settings:
        raise NoSubmissionResultsError(sub)

    if not all_submissions:
        rrids = [i["settings"].get("RRID", None) for i in settings]
        rrid = sorted([r for r in rrids if r])
        if rrid:
            rrid = rrid[-1]
            settings = [s for s in settings if s["settings"].get("RRID", rrid) == rrid]

    return [JobAggr(i["id"], aggregate=False, with_aggregate=i["withAggregate"]) for i in settings]


def get_submission_settings_data(
    token: dict[str, str], number: int, submission_type: str | None = None
) -> Sequence[Data]:
    log.info("Fetching settings for submission %s:%s", submission_type or DEFAULT_SUBMISSION_TYPE, number)
    params = {}
    if submission_type:
        params["type"] = submission_type
    data = get_json("api/incident_settings/" + f"{number}", headers=token, params=params)
    if "error" in data:
        log.warning("Submission %s:%s error: %s", submission_type or DEFAULT_SUBMISSION_TYPE, number, data["error"])
        return []

    return [
        Data(
            number,
            submission_type or DEFAULT_SUBMISSION_TYPE,
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


def get_submission_results(sub: int, token: dict[str, Any], submission_type: str | None = None) -> list[dict[str, Any]]:
    settings = get_submission_settings(sub, token, all_submissions=False, submission_type=submission_type)

    def _get_job_data(job_aggr: JobAggr) -> list[dict[str, Any]]:
        data = get_json("api/jobs/incident/" + f"{job_aggr.id}", headers=token)
        if "error" in data:
            raise ValueError(data["error"])
        return data

    all_data = (_get_job_data(job_aggr) for job_aggr in settings)
    return list(chain.from_iterable(all_data))


def get_aggregate_settings(sub: int, token: dict[str, str], submission_type: str | None = None) -> list[JobAggr]:
    params = {}
    if submission_type:
        params["type"] = submission_type
    settings = get_json(f"api/update_settings/{sub}", headers=token, params=params)
    if not settings:
        raise NoAggregateResultsError(sub)

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
            "aggregate",
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


def get_aggregate_results(sub: int, token: dict[str, Any], submission_type: str | None = None) -> list[dict[str, Any]]:
    settings = get_aggregate_settings(sub, token, submission_type=submission_type)

    def _get_job_data(job_aggr: JobAggr) -> list[dict[str, Any]]:
        data = get_json("api/jobs/update/" + f"{job_aggr.id}", headers=token)
        if "error" in data:
            raise ValueError(data["error"])
        return data

    all_data = (_get_job_data(job_aggr) for job_aggr in settings)
    return list(chain.from_iterable(all_data))


def update_submissions(token: dict[str, str], data: list[dict[str, Any]], **kwargs: Any) -> int:
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
            log.info("QEM Dashboard submissions updated successfully")
        else:
            log.error("QEM Dashboard submission sync failed: Status %s", ret.status_code)
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
