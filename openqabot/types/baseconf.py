# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from abc import ABC, abstractmethod, abstractstaticmethod
from typing import Any, Dict, List, Optional, Union

from openqabot import DEPRIORITIZE_LIMIT

from .incident import Incident


class BaseConf(ABC):
    def __init__(
        self,
        product: str,
        product_repo: Optional[Union[List[str], str]],
        product_version: Optional[str],
        settings: Dict[str, Any],
        _config: Dict[str, Any],  # Consider to remove and adapt code
    ) -> None:
        self.product = product
        self.product_repo = product_repo
        self.product_version = product_version
        self.settings = settings

    @abstractmethod
    def __call__(
        self,
        incidents: List[Incident],
        token: Dict[str, str],
        ci_url: Optional[str],
        *,
        ignore_onetime: bool,
    ) -> List[Dict[str, Any]]:
        pass

    @abstractstaticmethod
    def normalize_repos(config: Dict[str, Any]) -> Dict[str, Any]:
        pass

    def filter_embargoed(self, flavor: str) -> bool:
        return any(k.startswith("PUBLIC") for k in self.settings) or any(
            flavor.startswith(s) for s in ("Azure", "EC2", "GCE")
        )

    @staticmethod
    def set_obsoletion(settings: dict) -> None:
        if "_OBSOLETE" not in settings:
            settings["_DEPRIORITIZEBUILD"] = 1
            if DEPRIORITIZE_LIMIT is not None:
                settings["_DEPRIORITIZE_LIMIT"] = DEPRIORITIZE_LIMIT
