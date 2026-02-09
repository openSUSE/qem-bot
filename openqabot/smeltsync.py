# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Sync SMELT incidents to dashboard."""

from __future__ import annotations

from logging import getLogger
from operator import itemgetter
from pprint import pformat
from typing import TYPE_CHECKING, Any

from .config import settings
from .loader.qem import update_submissions
from .loader.smelt import get_active_submission_ids, get_submissions

if TYPE_CHECKING:
    from argparse import Namespace

log = getLogger("bot.smeltsync")


class SMELTSync:
    """Synchronization of SMELT incidents to dashboard."""

    def __init__(self, args: Namespace) -> None:
        """Initialize the SMELTSync class."""
        self.dry: bool = args.dry
        self.token: dict[str, str] = {"Authorization": "Token " + args.token}
        self.submissions = get_submissions(get_active_submission_ids())
        self.retry = args.retry

    def __call__(self) -> int:
        """Run the synchronization process."""
        log.info("Syncing SMELT incidents to QEM Dashboard")

        data = self.create_list(self.submissions)
        log.info("Updating %d submissions on QEM Dashboard", len(data))
        log.debug("Data: %s", pformat(data))

        if self.dry:
            log.info("Dry run: Skipping dashboard update")
            return 0
        return update_submissions(self.token, data, retry=self.retry)

    @staticmethod
    def review_rrequest(request_set: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Find the latest relevant release request from a set of requests."""
        valid = ("new", "review", "accepted", "revoked")
        if not request_set:
            return None
        rr = max(request_set, key=itemgetter("requestId"))
        return rr if rr["status"]["name"] in valid else None

    @staticmethod
    def is_inreview(rr_number: dict[str, Any]) -> bool:
        """Check if a release request is currently in review."""
        return bool(rr_number["reviewSet"]) and rr_number["status"]["name"] == "review"

    @staticmethod
    def is_revoked(rr_number: dict[str, Any]) -> bool:
        """Check if a release request has been revoked."""
        return bool(rr_number["reviewSet"]) and rr_number["status"]["name"] == "revoked"

    @staticmethod
    def is_accepted(rr_number: dict[str, Any]) -> bool:
        """Check if a release request has been accepted or is new."""
        return rr_number["status"]["name"] in {"accepted", "new"}

    @staticmethod
    def has_qam_review(rr_number: dict[str, Any]) -> bool:
        """Check if a release request has an active QAM review."""
        if not rr_number["reviewSet"]:
            return False
        rr = (r for r in rr_number["reviewSet"] if r["assignedByGroup"])
        review = [r for r in rr if r["assignedByGroup"]["name"] == "qam-openqa"]
        return bool(review) and review[0]["status"]["name"] in {"review", "new"}

    @classmethod
    def create_record(cls, sub: dict[str, Any]) -> dict[str, Any]:
        """Create a dashboard-compatible record from a SMELT incident."""
        submission = {}
        submission["isActive"] = True

        in_review = False
        approved = False
        in_review_qam = False
        revoked = False
        rr_id = None

        rr = cls.review_rrequest(sub["requestSet"])
        if rr:
            in_review = cls.is_inreview(rr)
            approved = cls.is_accepted(rr)
            in_review_qam = cls.has_qam_review(rr)
            revoked = cls.is_revoked(rr)
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
        submission["type"] = settings.default_submission_type

        return submission

    @classmethod
    def create_list(cls, submissions: list[Any]) -> list[dict[str, Any]]:
        """Create a list of dashboard-compatible records from SMELT incidents."""
        return [cls.create_record(sub) for sub in submissions]
