# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Base configuration type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .submission import Submission


@dataclass
class JobConfig:
    """Job configuration details."""

    product: str
    product_repo: list[str] | str | None
    product_version: str | None
    settings: dict[str, Any]
    config: dict[str, Any]
    global_excluded_packages: list[str] | None = None


class BaseConf(ABC):
    """Base class for bot configurations."""

    def __init__(self, config: JobConfig) -> None:
        """Initialize the BaseConf class."""
        self.product = config.product
        self.product_repo = config.product_repo
        self.product_version = config.product_version
        self.settings = config.settings
        self.global_excluded_packages = config.global_excluded_packages

    def is_globally_excluded(self, submission: Submission) -> bool:
        """Check if a submission matches the central (cross-product) blocklist."""
        return bool(self.global_excluded_packages) and submission.contains_package(self.global_excluded_packages)

    @abstractmethod
    def __call__(
        self,
        submissions: list[Submission],
        ci_url: str | None,
        *,
        ignore_onetime: bool,
    ) -> list[dict[str, Any]]:
        """Run the configuration's main processing logic."""
        # pragma: no cover

    @staticmethod
    @abstractmethod
    def normalize_repos(config: dict[str, Any]) -> dict[str, Any]:
        """Normalize repository configuration."""
        # pragma: no cover

    def filter_embargoed(self, flavor: str) -> bool:
        """Check if embargoed submissions should be filtered out for a given flavor."""
        return any(k.startswith("PUBLIC") for k in self.settings) or any(
            flavor.startswith(s) for s in ("Azure", "EC2", "GCE")
        )
