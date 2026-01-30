# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Base configuration type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .submission import Submission


@dataclass
class JobConfig:
    product: str
    product_repo: list[str] | str | None
    product_version: str | None
    settings: dict[str, Any]
    config: dict[str, Any]


class BaseConf(ABC):
    def __init__(self, config: JobConfig) -> None:
        """Initialize the BaseConf class."""
        self.product = config.product
        self.product_repo = config.product_repo
        self.product_version = config.product_version
        self.settings = config.settings

    @abstractmethod
    def __call__(
        self,
        submissions: list[Submission],
        token: dict[str, str],
        ci_url: str | None,
        *,
        ignore_onetime: bool,
    ) -> list[dict[str, Any]]:
        pass  # pragma: no cover

    @staticmethod
    @abstractmethod
    def normalize_repos(config: dict[str, Any]) -> dict[str, Any]:
        pass  # pragma: no cover

    def filter_embargoed(self, flavor: str) -> bool:
        return any(k.startswith("PUBLIC") for k in self.settings) or any(
            flavor.startswith(s) for s in ("Azure", "EC2", "GCE")
        )
