# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from functools import lru_cache
from logging import getLogger
from typing import List
from urllib.error import HTTPError

import osc.conf
import osc.core
import re

from openqa_client.exceptions import RequestError
from openqabot.errors import NoResultsError
from openqabot.openqa import openQAInterface

from . import OBS_GROUP, OBS_MAINT_PRJ, OBS_URL, QEM_DASHBOARD
from .loader.qem import (
    IncReq,
    JobAggr,
    get_aggregate_settings,
    get_incident_settings,
    get_incidents_approver,
    get_single_incident,
)
from .utils import retry3 as requests

log = getLogger("bot.approver")


def _handle_http_error(e: HTTPError, inc: IncReq) -> bool:
    if e.code == 403:
        log.info(
            "Received '%s'. Request %s likely already approved, ignoring"
            % (e.reason, inc.req)
        )
        return True
    elif e.code == 404:
        log.info(
            "Received '%s'. Request %s removed or problem on OBS side, ignoring"
            % (e.reason, inc.req)
        )
        return False
    else:
        log.error(
            "Recived error %s, reason: '%s' for Request %s - problem on OBS side"
            % (e.code, e.reason, inc.req)
        )
        return False


class Approver:
    def __init__(self, args: Namespace) -> None:
        self.dry = args.dry
        self.single_incident = args.incident
        self.token = {"Authorization": "Token {}".format(args.token)}
        self.all_incidents = args.all_incidents
        self.client = openQAInterface(args.openqa_instance)

    def __call__(self) -> int:
        log.info("Start approving incidents in IBS")
        increqs = (
            get_single_incident(self.token, self.single_incident)
            if self.single_incident
            else get_incidents_approver(self.token)
        )

        overall_result = True
        incidents_to_approve = [inc for inc in increqs if self._approvable(inc)]

        log.info("Incidents to approve:")
        for inc in incidents_to_approve:
            log.info(OBS_MAINT_PRJ + ":%s:%s" % (str(inc.inc), str(inc.req)))

        if not self.dry:
            osc.conf.get_config(override_apiurl=OBS_URL)
            for inc in incidents_to_approve:
                overall_result &= self.osc_approve(inc)

        log.info("End of bot run")

        return 0 if overall_result else 1

    def _approvable(self, inc: IncReq) -> bool:
        try:
            i_jobs = get_incident_settings(inc.inc, self.token, self.all_incidents)
        except NoResultsError as e:
            log.info(e)
            return False
        try:
            u_jobs = get_aggregate_settings(inc.inc, self.token)
        except NoResultsError as e:
            log.info(e)

            if any(i.withAggregate for i in i_jobs):
                log.info("Aggregate missing for %s" % str(inc.inc))
                return False

            u_jobs = []

        if not self.get_incident_result(i_jobs, "api/jobs/incident/", inc.inc):
            log.info(
                "Inc %s has at least one failed job in incident tests" % str(inc.inc)
            )
            return False

        if any(i.withAggregate for i in i_jobs):
            if not self.get_incident_result(u_jobs, "api/jobs/update/", inc.inc):
                log.info(
                    "Inc %s has at least one failed job in aggregate tests"
                    % str(inc.inc)
                )
                return False

        # everything is green --> add incident to approve list
        return True

    @lru_cache(maxsize=512)
    def is_job_marked_acceptable_for_incident(self, job: JobAggr, inc: int) -> bool:
        regex = re.compile(r"\@review\:acceptable_for\:incident_%s\:(.+)" % inc)
        try:
            for comment in self.client.get_job_comments(job.job_id):
                if regex.match(comment["text"]):
                    return True
        except RequestError:
            pass
        return False

    @lru_cache(maxsize=128)
    def get_jobs(self, job: JobAggr, api: str, inc: int) -> bool:
        results = requests.get(
            QEM_DASHBOARD + api + str(job.job_id), headers=self.token
        ).json()

        # keep jobs explicitly marked as acceptable for this incident by openQA comments
        for res in results:
            ok_job = res["status"] == "passed"
            if ok_job:
                continue
            if self.is_job_marked_acceptable_for_incident(job, inc):
                log.info(
                    "Ignoring failed job %s for incident %s due to openQA comment"
                    % (job.job_id, inc)
                )
                res["status"] = "passed"
            else:
                log.info(
                    "Found failed, not-ignored job %s for incident %s"
                    % (job.job_id, inc)
                )
                break

        if not results:
            raise NoResultsError("Job %s not found " % str(job.job_id))

        return all(r["status"] == "passed" for r in results)

    def get_incident_result(self, jobs: List[JobAggr], api: str, inc: int) -> bool:
        res = False

        for job in jobs:
            try:
                res = self.get_jobs(job, api, inc)
            except NoResultsError as e:
                log.info(e)
                continue
            if not res:
                return False

        return res

    @staticmethod
    def osc_approve(inc: IncReq) -> bool:

        msg = (
            "Request accepted for '" + OBS_GROUP + "' based on data in " + QEM_DASHBOARD
        )
        log.info(
            "Accepting review for "
            + OBS_MAINT_PRJ
            + ":%s:%s" % (str(inc.inc), str(inc.req))
        )

        try:
            osc.core.change_review_state(
                apiurl=OBS_URL,
                reqid=str(inc.req),
                newstate="accepted",
                by_group=OBS_GROUP,
                message=msg,
            )
        except HTTPError as e:
            return _handle_http_error(e, inc)
        except Exception as e:
            log.exception(e)
            return False

        return True
