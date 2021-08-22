from argparse import Namespace
from logging import getLogger
from operator import itemgetter
from pprint import pformat
from typing import Any, Dict, List

import requests

from . import QEM_DASHBOARD
from .loader.smelt import get_active_incidents, get_incidents

logger = getLogger("bot.smeltsync")


class SMELTSync:
    def __init__(self, args: Namespace) -> None:
        self.dry: bool = args.dry
        self.token: Dict[str, str] = {"Authorization": "Token " + args.token}
        self.incidents = get_incidents(get_active_incidents())

    def __call__(self) -> int:
        logger.info("Start syncing incidents from smelt to dashboard")

        data = self._create_list(self.incidents)
        logger.info("Updating info about %s incidents" % str(len(data)))

        try:
            if not self.dry:
                ret = requests.patch(
                    QEM_DASHBOARD + "api/incidents", headers=self.token, json=data
                )
        except Exception as e:
            logger.exception(e)
            return 1
        else:
            rt = 0
            if not self.dry and ret.status_code == 200:
                logger.info("Smelt Incidents updated")
            else:
                logger.error("Smelt Incidents wern't synced to dashboard")
                rt = 1

        logger.debug("Data: %s" % pformat(data))

        return rt

    @staticmethod
    def _review_rrequest(requestSet):
        if not requestSet:
            return None
        else:
            rr = sorted(requestSet, key=itemgetter("requestId"), reverse=True)[0]
            if rr["status"]["name"] in ("new", "review", "accepted", "revoked"):
                return rr
            else:
                return None

    @staticmethod
    def _is_inreview(rr_number) -> bool:
        if rr_number["reviewSet"]:
            if rr_number["status"]["name"] == "review":
                return True
            else:
                return False
        else:
            return False

    @staticmethod
    def _is_revoked(rr_number) -> bool:
        if rr_number["reviewSet"]:
            if rr_number["status"]["name"] == "revoked":
                return True
            else:
                return False
        else:
            return False

    @staticmethod
    def _is_accepted(rr_number) -> bool:
        if (
            rr_number["status"]["name"] == "accepted"
            or rr_number["status"]["name"] == "new"
        ):
            return True
        else:
            return False

    @staticmethod
    def _has_qam_review(rr_number) -> bool:
        if rr_number["reviewSet"]:
            rr = (r for r in rr_number["reviewSet"] if r["assignedByGroup"])
            review = [r for r in rr if r["assignedByGroup"]["name"] == "qam-openqa"]
            if review and review[0]["status"]["name"] in ("review", "new"):
                return True
        return False

    @classmethod
    def _create_record(cls, inc):

        incident = {}
        incident["isActive"] = True

        rr_number = cls._review_rrequest(inc["requestSet"])
        if rr_number:
            inReview = cls._is_inreview(rr_number)
            approved = cls._is_accepted(rr_number)
            inReviewQAM = cls._has_qam_review(rr_number)
            revoked = cls._is_revoked(rr_number)
            # beware . this must be last.
            rr_number = rr_number["requestId"]
        # no request in requestest --> defaut values
        else:
            inReview = False
            approved = False
            inReviewQAM = False
            revoked = False

        if approved or revoked:
            incident["isActive"] = False

        incident["project"] = inc["project"]
        incident["number"] = int(inc["project"].split(":")[-1])
        incident["emu"] = inc["emu"]
        incident["packages"] = [package["name"] for package in inc["packages"]]
        incident["channels"] = [repo["name"] for repo in inc["repositories"]]
        incident["inReview"] = inReview
        incident["approved"] = approved
        incident["rr_number"] = rr_number
        incident["inReviewQAM"] = inReviewQAM

        return incident

    @classmethod
    def _create_list(cls, incidents: List[Any]) -> List[Dict[str, Any]]:
        return [cls._create_record(inc) for inc in incidents]
