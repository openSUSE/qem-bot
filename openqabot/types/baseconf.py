# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from abc import ABC, abstractmethod, abstractstaticmethod
from typing import Any

from .incident import Incident


class BaseConf(ABC):
    def __init__(
        self,
        product: str,
        product_repo: list[str] | str | None,
        product_version: str | None,
        settings: dict[str, Any],
        _config: dict[str, Any],  # Consider to remove and adapt code
    ) -> None:
        self.product = product
        self.product_repo = product_repo
        self.product_version = product_version
        self.settings = settings

    @abstractmethod
    def __call__(
        self,
        incidents: list[Incident],
        token: dict[str, str],
        ci_url: str | None,
        *,
        ignore_onetime: bool,
    ) -> list[dict[str, Any]]:
        pass

    @abstractstaticmethod
    def normalize_repos(config: dict[str, Any]) -> dict[str, Any]:
        pass

    def filter_embargoed(self, flavor: str) -> bool:
        return any(k.startswith("PUBLIC") for k in self.settings) or any(
            flavor.startswith(s) for s in ("Azure", "EC2", "GCE")
        )
