# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from argparse import Namespace
from logging import getLogger
from operator import itemgetter
from pprint import pformat
from typing import Any

from .config import DEFAULT_SUBMISSION_TYPE
from .loader.qem import update_submissions
from .loader.smelt import get_active_submission_ids, get_submissions

log = getLogger("bot.smeltsync")


class SMELTSync:
    def __init__(self, args: Namespace) -> None:
        self.dry: bool = args.dry
        self.token: dict[str, str] = {"Authorization": "Token " + args.token}
        self.submissions = get_submissions(get_active_submission_ids())
        self.retry = args.retry

    def __call__(self) -> int:
        log.info("Syncing SMELT incidents to QEM Dashboard")

        data = self._create_list(self.submissions)
        log.info("Updating %d submissions on QEM Dashboard", len(data))
        log.debug("Data: %s", pformat(data))

        if self.dry:
            log.info("Dry run: Skipping dashboard update")
            return 0
        return update_submissions(self.token, data, retry=self.retry)

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
        if not rr_number["reviewSet"]:
            return False
        rr = (r for r in rr_number["reviewSet"] if r["assignedByGroup"])
        review = [r for r in rr if r["assignedByGroup"]["name"] == "qam-openqa"]
        return bool(review) and review[0]["status"]["name"] in {"review", "new"}

    @classmethod
    def _create_record(cls, sub: dict[str, Any]) -> dict[str, Any]:
        submission = {}
        submission["isActive"] = True

        in_review = False
        approved = False
        in_review_qam = False
        revoked = False
        rr_id = None

        rr = cls._review_rrequest(sub["requestSet"])
        if rr:
            in_review = cls._is_inreview(rr)
            approved = cls._is_accepted(rr)
            in_review_qam = cls._has_qam_review(rr)
            revoked = cls._is_revoked(rr)
            rr_id = rr["requestId"]

        if approved or revoked:
            submission["isActive"] = False

        submission["project"] = sub["project"]
        submission["number"] = int(sub["project"].split(":")[-1])
        submission["emu"] = sub["emu"]
        submission["packages"] = [package["name"] for package in sub["packages"]]
        submission["channels"] = [repo["name"] for repo in sub["repositories"]]
        submission["inReview"] = in_review
        submission["approved"] = approved
        submission["rr_number"] = rr_id
        submission["inReviewQAM"] = in_review_qam
        submission["embargoed"] = bool(sub["crd"])
        submission["priority"] = sub["priority"]
        submission["type"] = DEFAULT_SUBMISSION_TYPE

        return submission

    @classmethod
    def _create_list(cls, submissions: list[Any]) -> list[dict[str, Any]]:
        return [cls._create_record(sub) for sub in submissions]
