# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Tests for get_configs_from_path utility."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openqabot.utils import get_configs_from_path


@dataclass
class MockConfig:
    """Mock configuration class for testing."""

    distri: str
    settings: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_config_entry(cls, entry: dict[str, Any]) -> "MockConfig":
        """Create a MockConfig from a dictionary entry."""
        return cls(distri=entry["distri"], settings=entry.get("settings", {}))


def test_get_configs_from_path_dict(tmp_path: Path) -> None:
    """Test loading configurations from a dictionary-style YAML."""
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        """
trigger_config:
  sle:
    distri: sle
  openSUSE:
    distri: opensuse
"""
    )

    configs = get_configs_from_path(config_file, "trigger_config", MockConfig.from_config_entry)
    assert len(configs) == 2
    distris = {c.distri for c in configs}
    assert distris == {"sle", "opensuse"}


def test_get_configs_from_path_list(tmp_path: Path) -> None:
    """Test loading configurations from a list-style YAML."""
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        """
trigger_config:
  - distri: sle
  - distri: opensuse
"""
    )

    configs = get_configs_from_path(config_file, "trigger_config", MockConfig.from_config_entry)
    assert len(configs) == 2
    distris = {c.distri for c in configs}
    assert distris == {"sle", "opensuse"}


def test_get_configs_from_path_with_settings(tmp_path: Path) -> None:
    """Test loading configurations with global settings merge."""
    config_file = tmp_path / "config.yml"
    config_file.write_text(
        """
settings:
  GLOBAL: value
trigger_config:
  sle:
    distri: sle
    settings:
      LOCAL: local_value
"""
    )

    configs = get_configs_from_path(config_file, "trigger_config", MockConfig.from_config_entry)
    assert len(configs) == 1
    assert configs[0].distri == "sle"
    assert configs[0].settings == {"GLOBAL": "value", "LOCAL": "local_value"}
