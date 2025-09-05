# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from abc import ABCMeta, abstractmethod, abstractstaticmethod
from typing import Any, Dict, List, Optional

from .incident import Incident


class BaseConf(metaclass=ABCMeta):
    def __init__(
        self,
        product: str,
        product_repo: Optional[str],
        settings,
        config,  # pylint: disable=unused-argument
    ) -> None:
        self.product = product
        self.product_repo = product_repo
        self.settings = settings

    @abstractmethod
    def __call__(
        self,
        incidents: List[Incident],
        token: Dict[str, str],
        ci_url: Optional[str],
        ignore_onetime: bool,
    ) -> List[Dict[str, Any]]:
        pass

    @abstractstaticmethod
    def normalize_repos(config):
        pass

    def filter_embargoed(self, flavor: str) -> bool:
        return any(k.startswith("PUBLIC") for k in self.settings) or any(
            flavor.startswith(s) for s in ("Azure", "EC2", "GCE")
        )

    @staticmethod
    def set_obsoletion(settings: dict) -> None:
        if "_OBSOLETE" not in settings:
            settings["_DEPRIORITIZEBUILD"] = 1
