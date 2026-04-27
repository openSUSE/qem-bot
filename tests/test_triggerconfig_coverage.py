# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test TriggerConfig coverage."""

from typing import Any

from openqabot.loader.triggerconfig import TriggerConfig


def test_trigger_config_str() -> None:
    """Test TriggerConfig string representation."""
    config = TriggerConfig(distri="sle", flavor="Online")
    assert str(config) == "sle (no settings)"

    config2 = TriggerConfig(distri="sle", flavor="Online", settings={"FOO": "BAR"})
    assert str(config2) == "sle ({'FOO': 'BAR'})"


def test_trigger_config_from_config_entry() -> None:
    """Test TriggerConfig creation from config entry."""
    entry: dict[str, Any] = {"distri": "sle", "flavor": "Online", "settings": {"FOO": "BAR"}}
    config = TriggerConfig.from_config_entry(entry)
    assert config.distri == "sle"
    assert config.flavor == "Online"
    assert config.settings == {"FOO": "BAR"}

    entry2: dict[str, Any] = {"distri": "sle"}
    config2 = TriggerConfig.from_config_entry(entry2)
    assert config2.distri == "sle"
    assert config2.flavor == "any"
    assert config2.settings == {}
