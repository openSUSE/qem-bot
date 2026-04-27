# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Trigger configuration loader."""

from __future__ import annotations

import pprint
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TriggerConfig:
    """Base configuration for product increments."""

    distri: str
    flavor: str
    settings: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        """Return a string representation of the increment configuration."""
        settings_str = pprint.pformat(self.settings, compact=True, depth=1) if self.settings else "no settings"
        return f"{self.distri} ({settings_str})"

    @classmethod
    def from_config_entry(cls, entry: dict[str, Any]) -> TriggerConfig:
        """Create an BaseConfig from a dictionary entry."""
        return cls(
            distri=entry["distri"],
            flavor=entry.get("flavor", "any"),
            settings=entry.get("settings", {}),
        )
