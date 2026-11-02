# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""QEM Dashboard loader."""

from __future__ import annotations

import sys
from http import HTTPStatus
from itertools import chain
from logging import getLogger
from operator import itemgetter
from pprint import pformat
from typing import TYPE_CHECKING, Any, NamedTuple

import requests

import openqabot.config as config_module
from openqabot import dashboard
from openqabot.errors import LoaderQemError, NoResultsError, SubmissionArgError
from openqabot.types.submission import Submission, sort_packages
from openqabot.types.submission_key import SubmissionKey
from openqabot.types.types import Data

if TYPE_CHECKING:
    from collections.abc import Sequence

log = getLogger("bot.loader.qem")


class SubReq(NamedTuple):
    """Dashboard submission, its release request and its identity fields.

    ``sub``, ``type`` and ``project`` together form the dashboard incident key;
    ``req`` is the OBS release request ID.

    ``scminfo`` is the submission's ``scminfo`` on the dashboard: the revision
    OBS reported for the build of a Gitea PR. ``scm_info`` is a separate value
    read from a dashboard key the dashboard never sends, so it stays empty.
    """

    sub: int
    req: int
    type: str
    project: str
    url: str | None = None
    scm_info: str | None = None
    submission: Submission | None = None
    scminfo: str | None = None

    @property
    def key(self) -> SubmissionKey:
        """Dashboard incident key of this submission."""
        return SubmissionKey(self.type, self.project, self.sub)

    @classmethod
    def from_dashboard(cls, d: dict) -> SubReq | None:
        """Build a SubReq from a dashboard submission dict.

        Returns ``None`` and logs a warning only when the incident key fields
        (``number``, ``rr_number``, ``type``, ``project``) are missing, so one
        unaddressable incident cannot abort a batch approval run.

        A ``KeyError`` raised by ``Submission.create`` means the incident is
        addressable but its body lacks a field such as ``inReview`` or ``emu``.
        The incident is then kept with ``submission=None`` and an error is
        logged, mirroring how empty channels/packages already yield a usable
        ``SubReq`` without a ``Submission``: dropping it would silently remove
        a real approval from the batch.
        """
        try:
            number = d["number"]
            rr_number = d["rr_number"]
            s_type = d["type"]
            project = d["project"]
        except KeyError as e:
            log.warning("Dashboard incident %s skipped: missing identity field %s", d.get("number"), e)
            return None

        try:
            submission = Submission.create(d)
        except KeyError:
            log.exception(
                "Dashboard incident %s:%s has incomplete data, continuing without submission details",
                s_type,
                number,
            )
            submission = None

        return cls(
            number,
            rr_number,
            s_type,
            project,
            url=d.get("url", ""),
            scm_info=d.get("scm_info", ""),
            submission=submission,
            scminfo=d.get("scminfo") or None,
        )


class JobAggr(NamedTuple):
    """Job and aggregate information."""

    id: int
    aggregate: bool
    with_aggregate: bool = False


class NoSubmissionResultsError(NoResultsError):
    """Raised when no submission results are found."""

    def __init__(self, sub: int) -> None:
        """Initialize the NoSubmissionResultsError class."""
        super().__init__(f"No submission test results found for {sub}")


class NoAggregateResultsError(NoResultsError):
    """Raised when no aggregate results are found."""

    def __init__(self, sub: int) -> None:
        """Initialize the NoAggregateResultsError class."""
        super().__init__(f"No aggregate test results found for {sub}")


def _get_submission(subkey: SubmissionKey) -> dict:
    """Fetch a single submission's raw data from the dashboard."""
    return dashboard.get_json(
        f"api/incidents/{subkey.number}",
        headers=config_module.settings.dashboard_token_dict,
        params=subkey.to_dashboard_params(),
    )


def get_submissions(submission: str | None = None) -> list[Submission]:
    """Fetch all or a specific submission from the dashboard and wrap them in Submission objects.

    ``submission`` is given as ``<type>:<project>:<id>``; an unparsable value
    terminates the process with ``SystemExit``.
    """
    if submission:
        try:
            key = SubmissionKey.parse(submission)
        except SubmissionArgError as e:
            raise SystemExit(str(e)) from e
        res = _get_submission(key)
        if isinstance(res, dict) and "error" in res:
            log.error("Submission %s was not found on the QEM Dashboard or is invalid.", key)
            log.error("Dashboard error details: %s", res.get("error"))
            log.error("Please verify that the submission ID is correct and active on the dashboard.")
            sys.exit(1)
        submissions = [res]
    else:
        submissions = dashboard.get_json(
            "api/incidents",
            headers=config_module.settings.dashboard_token_dict,
            verify=not config_module.settings.insecure,
        )

    if "error" in submissions:
        raise LoaderQemError(submissions)

    return [sub for s in submissions if (sub := Submission.create(s))]


def get_active_submissions(submission_type: str | None = None) -> Sequence[SubmissionKey]:
    """Fetch the keys of all active submissions from the dashboard.

    Incidents missing one of the identity fields are logged and skipped instead
    of raising, so a single malformed record cannot abort a batch results sync.
    """
    params = {}
    if submission_type:
        params["type"] = submission_type
    data = dashboard.get_json("api/incidents", headers=config_module.settings.dashboard_token_dict, params=params)

    active: set[SubmissionKey] = set()
    for incident in data:
        try:
            active.add(SubmissionKey.from_dashboard(incident))
        except KeyError as e:
            log.warning("Dashboard incident %s skipped: missing identity field %s", incident.get("number"), e)
    return list(active)


def get_submissions_approver() -> list[SubReq]:
    """Fetch submissions that are ready for QAM review."""
    submissions = dashboard.get_json("api/incidents", headers=config_module.settings.dashboard_token_dict)
    return [
        subreq
        for incident in submissions
        if incident.get("inReviewQAM")
        if (subreq := SubReq.from_dashboard(incident)) is not None
    ]


def get_single_submission(key: SubmissionKey) -> list[SubReq]:
    """Fetch a single submission and wrap it in a list of SubReq objects.

    Returns an empty list when the dashboard does not know the submission (it
    answers with ``{"error": ...}``) or when the returned entry cannot be
    turned into a ``SubReq``.
    """
    submission = _get_submission(key)
    if isinstance(submission, dict) and "error" in submission:
        log.warning(
            "Submission %s not found on the dashboard: %s",
            key,
            submission.get("error"),
        )
        return []
    subreq = SubReq.from_dashboard(submission)
    if subreq is None:
        log.warning("Submission %s is missing required fields on the dashboard", key)
        return []
    return [subreq]


def _keep_current_round(
    settings: list[dict[str, Any]], submission_type: str, scminfo: str | None
) -> list[dict[str, Any]]:
    """Drop settings that belong to an earlier revision of the submission.

    Rescheduling a ``version``/``flavor``/``arch`` combination overwrites its
    settings row, but the jobs of earlier rounds stay linked to it, so the jobs
    of a submission mix revisions. OBS submissions separate rounds with the
    monotonically increasing ``RRID``. Gitea PRs have no release request; their
    settings carry the commit OBS built for them as ``SCMINFO``. Settings without
    that marker predate it and are kept, so the filter never empties the result on
    its own.
    """
    if submission_type == "git":
        if not scminfo:
            return settings
        return [s for s in settings if s["settings"].get("SCMINFO", scminfo) == scminfo]

    rrids = sorted([r for r in (s["settings"].get("RRID", None) for s in settings) if r])
    if not rrids:
        return settings
    rrid = rrids[-1]
    return [s for s in settings if s["settings"].get("RRID", rrid) == rrid]


def get_submission_settings(
    key: SubmissionKey,
    *,
    all_submissions: bool = False,
    scminfo: str | None = None,
) -> list[JobAggr]:
    """Fetch job settings associated with a submission.

    With ``scminfo`` set, settings of a Gitea PR that were created for another
    revision are dropped, so an empty result means "the recorded commit has no
    settings yet".
    """
    settings = dashboard.get_json(
        f"api/incident_settings/{key.number}",
        headers=config_module.settings.dashboard_token_dict,
        params=key.to_dashboard_params(),
    )
    if not settings:
        raise NoSubmissionResultsError(key.number)

    if not all_submissions:
        settings = _keep_current_round(settings, key.type, scminfo)

    return [JobAggr(i["id"], aggregate=False, with_aggregate=i["withAggregate"]) for i in settings]


def get_submission_settings_data(key: SubmissionKey) -> Sequence[Data]:
    """Fetch job settings data for a submission and wrap them in Data objects."""
    log.debug("Fetching settings for submission %s", key)
    data = dashboard.get_json(
        f"api/incident_settings/{key.number}",
        headers=config_module.settings.dashboard_token_dict,
        params=key.to_dashboard_params(),
    )
    if "error" in data:
        log.warning("Submission %s error: %s", key, data["error"])
        return []

    return [
        Data(
            key.number,
            key.type,
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


def get_submission_results(key: SubmissionKey, *, scminfo: str | None = None) -> list[dict[str, Any]]:
    """Fetch all test results associated with a submission."""
    settings = get_submission_settings(key, all_submissions=False, scminfo=scminfo)

    def _get_job_data(job_aggr: JobAggr) -> list[dict[str, Any]]:
        """Fetch job data for a specific settings ID."""
        data = dashboard.get_json(
            "api/jobs/incident/" + f"{job_aggr.id}", headers=config_module.settings.dashboard_token_dict
        )
        if "error" in data:
            raise ValueError(data["error"])
        return data

    all_data = (_get_job_data(job_aggr) for job_aggr in settings)
    return list(chain.from_iterable(all_data))


def get_aggregate_settings(key: SubmissionKey) -> list[JobAggr]:
    """Fetch aggregate job settings associated with a submission."""
    settings = dashboard.get_json(
        f"api/update_settings/{key.number}",
        headers=config_module.settings.dashboard_token_dict,
        params=key.to_dashboard_params(),
    )
    if not settings:
        raise NoAggregateResultsError(key.number)

    # we need a reverse sort due to doing a string comparison
    settings = sorted(settings, key=itemgetter("build"), reverse=True)
    # use all data from day (some jobs have set onetime=True)
    # which causes need to use data from both runs
    last_build = settings[0]["build"][:-2]
    return [JobAggr(i["id"], aggregate=True, with_aggregate=False) for i in settings if last_build in i["build"]]


def get_aggregate_settings_data(data: Data) -> Sequence[Data]:
    """Fetch aggregate job settings data for a product and architecture."""
    settings = dashboard.get_json(
        "api/update_settings",
        headers=config_module.settings.dashboard_token_dict,
        params={"product": data.product, "arch": data.arch},
    )
    if not settings:
        log.info("No aggregate settings found for product %s on arch %s", data.product, data.arch)
        return []

    log.debug("Resolving aggregate ID for data: %s", pformat(data))

    # use last three schedule
    return [data._replace(settings_id=s["id"], build=s["build"]) for s in settings[:3]]


def get_aggregate_results(key: SubmissionKey) -> list[dict[str, Any]]:
    """Fetch all aggregate test results associated with a submission."""
    settings = get_aggregate_settings(key)

    def _get_job_data(job_aggr: JobAggr) -> list[dict[str, Any]]:
        """Fetch job data for a specific aggregate settings ID."""
        data = dashboard.get_json(
            "api/jobs/update/" + f"{job_aggr.id}", headers=config_module.settings.dashboard_token_dict
        )
        if "error" in data:
            raise ValueError(data["error"])
        return data

    all_data = (_get_job_data(job_aggr) for job_aggr in settings)
    return list(chain.from_iterable(all_data))


def update_submissions(data: list[dict[str, Any]], **kwargs: Any) -> int:  # ruff: ignore[any-type]
    """Synchronize submission records with the dashboard."""
    retry = kwargs.get("retry", 0)
    query_params = kwargs.get("params", {})
    for record in data:
        if packages := record.get("packages"):
            record["packages"] = sort_packages(packages)
    while retry >= 0:
        retry -= 1
        try:
            ret = dashboard.patch(
                "api/incidents", headers=config_module.settings.dashboard_token_dict, params=query_params, json=data
            )
        except requests.exceptions.RequestException:
            log.exception("QEM Dashboard API request failed")
            return 1
        if ret.status_code == HTTPStatus.OK:
            log.info("QEM Dashboard submissions updated successfully")
        else:
            log.error("QEM Dashboard submission sync failed: Status %s", ret.status_code)
            error_text = ret.text
            if len(error_text):
                log.error("QEM Dashboard error response: %s", error_text)
            continue
        return 0
    return 2


def post_job(data: dict[str, Any]) -> None:
    """Create a new job record on the dashboard."""
    try:
        result = dashboard.put("api/jobs", headers=config_module.settings.dashboard_token_dict, json=data)
        if result.status_code != HTTPStatus.OK:
            log.error("Dashboard API error: Could not post job: %s", result.text)

    except requests.exceptions.RequestException:
        log.exception("QEM Dashboard API request failed")


def update_job(job_id: int, data: dict[str, Any]) -> None:
    """Update an existing job record on the dashboard."""
    try:
        result = dashboard.patch(f"api/jobs/{job_id}", headers=config_module.settings.dashboard_token_dict, json=data)
        if result.status_code != HTTPStatus.OK:
            log.error("Dashboard API error: Could not update job %s: %s", job_id, result.text)

    except requests.exceptions.RequestException:
        log.exception("QEM Dashboard API request failed")


def update_incident_reason(key: SubmissionKey, reason: str | None = None) -> None:
    """Update the rejection reason for a submission on the dashboard.

    The dashboard addresses an incident by its ``(number, project, type)`` key,
    which ``key`` carries in full.
    """
    try:
        result = dashboard.patch(
            f"api/incidents/{key.number}/rejection_reason",
            headers=config_module.settings.dashboard_token_dict,
            params=key.to_dashboard_params(),
            json={"rejection_reason": reason},
        )
        if result.status_code != HTTPStatus.OK:
            log.error(
                "Dashboard API error: Could not update rejection reason for incident %s: %s",
                key,
                result.text,
            )
    except requests.exceptions.RequestException:
        log.exception("QEM Dashboard API request failed")
