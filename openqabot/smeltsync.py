# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from logging import getLogger
from operator import itemgetter
from pprint import pformat
from typing import Any, Dict, List

from .loader.qem import update_incidents
from .loader.smelt import get_active_incidents, get_incidents

log = getLogger("bot.smeltsync")


class SMELTSync:
    def __init__(self, args: Namespace) -> None:
        self.dry: bool = args.dry
        self.token: Dict[str, str] = {"Authorization": "Token " + args.token}
        self.incidents = get_incidents(get_active_incidents())
        self.retry = args.retry

    def __call__(self) -> int:
        log.info("Starting to sync incidents from smelt to dashboard")

        data = self._create_list(self.incidents)
        log.info("Updating info about %s incidents", str(len(data)))
        log.debug("Data: %s", pformat(data))

        if not self.dry:
            ret = update_incidents(self.token, data, retry=self.retry)
        else:
            log.info("Dry run, nothing synced")
            ret = 0

        return ret

    @staticmethod
    def _review_rrequest(request_set):
        valid = ("new", "review", "accepted", "revoked")
        if not request_set:
            return None
        rr = sorted(request_set, key=itemgetter("requestId"), reverse=True)[0]
        return rr if rr["status"]["name"] in valid else None

    @staticmethod
    def _is_inreview(rr_number) -> bool:
        if rr_number["reviewSet"]:
            return rr_number["status"]["name"] == "review"
        return False

    @staticmethod
    def _is_revoked(rr_number) -> bool:
        if rr_number["reviewSet"]:
            return rr_number["status"]["name"] == "revoked"
        return False

    @staticmethod
    def _is_accepted(rr_number) -> bool:
        return (
            rr_number["status"]["name"] == "accepted"
            or rr_number["status"]["name"] == "new"
        )

    @staticmethod
    def _has_qam_review(rr_number) -> bool:
        if not rr_number["reviewSet"]:
            return False
        rr = (r for r in rr_number["reviewSet"] if r["assignedByGroup"])
        review = [r for r in rr if r["assignedByGroup"]["name"] == "qam-openqa"]
        return bool(review) and review[0]["status"]["name"] in ("review", "new")

    @classmethod
    def _create_record(cls, inc):
        incident = {}
        incident["isActive"] = True

        rr_number = cls._review_rrequest(inc["requestSet"])
        if rr_number:
            in_review = cls._is_inreview(rr_number)
            approved = cls._is_accepted(rr_number)
            in_review_qam = cls._has_qam_review(rr_number)
            revoked = cls._is_revoked(rr_number)
            # beware . this must be last.
            rr_number = rr_number["requestId"]
        # no request in requestest --> defaut values
        else:
            in_review = False
            approved = False
            in_review_qam = False
            revoked = False

        if approved or revoked:
            incident["isActive"] = False

        incident["project"] = inc["project"]
        incident["number"] = int(inc["project"].split(":")[-1])
        incident["emu"] = inc["emu"]
        incident["packages"] = [package["name"] for package in inc["packages"]]
        incident["channels"] = [repo["name"] for repo in inc["repositories"]]
        incident["inReview"] = in_review
        incident["approved"] = approved
        incident["rr_number"] = rr_number
        incident["inReviewQAM"] = in_review_qam
        incident["embargoed"] = bool(inc["crd"])

        return incident

    @classmethod
    def _create_list(cls, incidents: List[Any]) -> List[Dict[str, Any]]:
        return [cls._create_record(inc) for inc in incidents]
