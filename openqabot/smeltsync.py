# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from argparse import Namespace
from logging import getLogger
from operator import itemgetter
from pprint import pformat
from typing import Any

from .loader.qem import update_incidents
from .loader.smelt import get_active_incidents, get_incidents

log = getLogger("bot.smeltsync")


class SMELTSync:
    def __init__(self, args: Namespace) -> None:
        self.dry: bool = args.dry
        self.token: dict[str, str] = {"Authorization": "Token " + args.token}
        self.incidents = get_incidents(get_active_incidents())
        self.retry = args.retry

    def __call__(self) -> int:
        log.info("Syncing SMELT incidents to QEM Dashboard")

        data = self._create_list(self.incidents)
        log.info("Updating %d incidents on QEM Dashboard", len(data))
        log.debug("Data: %s", pformat(data))

        if self.dry:
            log.info("Dry run: Skipping dashboard update")
            return 0
        return update_incidents(self.token, data, retry=self.retry)

    @staticmethod
    def _review_rrequest(request_set: list[dict[str, Any]]) -> dict[str, Any] | None:
        valid = ("new", "review", "accepted", "revoked")
        if not request_set:
            return None
        rr = max(request_set, key=itemgetter("requestId"))
        return rr if rr["status"]["name"] in valid else None

    @staticmethod
    def _is_inreview(rr_number: dict[str, Any]) -> bool:
        return bool(rr_number["reviewSet"]) and rr_number["status"]["name"] == "review"

    @staticmethod
    def _is_revoked(rr_number: dict[str, Any]) -> bool:
        return bool(rr_number["reviewSet"]) and rr_number["status"]["name"] == "revoked"

    @staticmethod
    def _is_accepted(rr_number: dict[str, Any]) -> bool:
        return rr_number["status"]["name"] in {"accepted", "new"}

    @staticmethod
    def _has_qam_review(rr_number: dict[str, Any]) -> bool:
        return any(
            r
            and r.get("assignedByGroup", {}).get("name") == "qam-openqa"
            and r.get("status", {}).get("name") in {"review", "new"}
            for r in rr_number.get("reviewSet", [])
        )

    @classmethod
    def _create_record(cls, inc: dict[str, Any]) -> dict[str, Any]:
        incident = {}
        incident["isActive"] = True

        in_review = False
        approved = False
        in_review_qam = False
        revoked = False
        rr_id = None

        rr = cls._review_rrequest(inc["requestSet"])
        if rr:
            in_review = cls._is_inreview(rr)
            approved = cls._is_accepted(rr)
            in_review_qam = cls._has_qam_review(rr)
            revoked = cls._is_revoked(rr)
            rr_id = rr["requestId"]

        if approved or revoked:
            incident["isActive"] = False

        incident["project"] = inc["project"]
        incident["number"] = int(inc["project"].split(":")[-1])
        incident["emu"] = inc["emu"]
        incident["packages"] = [package["name"] for package in inc["packages"]]
        incident["channels"] = [repo["name"] for repo in inc["repositories"]]
        incident["inReview"] = in_review
        incident["approved"] = approved
        incident["rr_number"] = rr_id
        incident["inReviewQAM"] = in_review_qam
        incident["embargoed"] = bool(inc["crd"])
        incident["priority"] = inc["priority"]

        return incident

    @classmethod
    def _create_list(cls, incidents: list[Any]) -> list[dict[str, Any]]:
        return [cls._create_record(inc) for inc in incidents]
