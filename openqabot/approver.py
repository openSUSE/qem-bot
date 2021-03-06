# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from functools import lru_cache
from logging import getLogger
from typing import List

import osc.conf
import osc.core
from urllib.error import HTTPError
from openqabot.errors import NoResultsError

from . import QEM_DASHBOARD, OBS_GROUP, OBS_MAINT_PRJ, OBS_URL
from .loader.qem import (
    IncReq,
    JobAggr,
    get_incidents_approver,
    get_incident_settings,
    get_aggregate_settings,
)
from .requests import requests

logger = getLogger("bot.approver")


class Approver:
    def __init__(self, args: Namespace) -> None:
        self.dry = args.dry
        self.token = {"Authorization": "Token {}".format(args.token)}
        self.all_incidents = args.all_incidents

    def __call__(self) -> int:
        logger.info("Start approving incidents in IBS")

        increqs = get_incidents_approver(self.token)

        overall_result = True
        incidents_to_approve = []

        for inc in increqs:
            try:
                i_jobs = get_incident_settings(inc.inc, self.token, self.all_incidents)
            except NoResultsError as e:
                logger.info(e)
                continue
            try:
                u_jobs = get_aggregate_settings(inc.inc, self.token)
            except NoResultsError as e:
                logger.info(e)

                if any(i.withAggregate for i in i_jobs):
                    logger.info("Aggregate missing for %s" % str(inc.inc))
                    continue

                u_jobs = []

            if not self.get_incident_result(i_jobs, "api/jobs/incident/"):
                logger.info("Inc %s has failed job in incidents" % str(inc.inc))
                continue

            if any(i.withAggregate for i in i_jobs):
                if not self.get_incident_result(u_jobs, "api/jobs/update/"):
                    logger.info("Inc %s has failed job in aggregates" % str(inc.inc))
                    continue

            # everything is green --> approve inc
            incidents_to_approve.append(inc)

        if not self.dry:
            osc.conf.get_config(override_apiurl=OBS_URL)

            for inc in incidents_to_approve:
                overall_result &= self.osc_approve(inc)
        else:
            logger.info("Incidents to approve:")
            for inc in incidents_to_approve:
                logger.info(OBS_MAINT_PRJ + ":%s:%s" % (str(inc.inc), str(inc.req)))

        logger.info("End of bot run")

        return 0 if overall_result else 1

    @lru_cache(maxsize=128)
    def get_jobs(self, job: JobAggr, api: str) -> bool:
        results = requests.get(
            QEM_DASHBOARD + api + str(job.job_id), headers=self.token
        ).json()

        if not results:
            raise NoResultsError("Job %s not found " % str(job.job_id))

        return all(r["status"] == "passed" for r in results)

    def get_incident_result(self, jobs: List[JobAggr], api: str) -> bool:
        res = False

        for job in jobs:
            try:
                res = self.get_jobs(job, api)
            except NoResultsError as e:
                logger.info(e)
                continue
            if not res:
                return False

        return res

    @staticmethod
    def osc_approve(inc: IncReq) -> bool:

        msg = (
            "Request accepted for '" + OBS_GROUP + "' based on data in " + QEM_DASHBOARD
        )
        logger.info(
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
            if e.code == 403:
                logger.info(
                    "Received '%s'. Request %s likely already approved, ignoring"
                    % (e.reason, inc.req)
                )
                return True
            elif e.code == 404:
                logger.info(
                    "Received '%s'. Request %s removed or problem on OBS side, ignoring"
                    % (e.reason, inc.req)
                )
                return False
            else:
                logger.error(
                    "Recived error %s, reason: '%s' for Request %s - problem on OBS side"
                    % (e.code, e.reason, inc.req)
                )
                return False
        except Exception as e:
            logger.exception(e)
            return False

        return True
