# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test TriggerConfig coverage."""

from typing import Any

import pytest

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


def test_trigger_config_obs_repo_url() -> None:
    """Test generating OBS repository URL."""
    config = TriggerConfig(
        distri="sle",
        flavor="Online",
        project="SUSE/Products/SLES",
        branch="openSUSE-Leap-15.5",
        repo_template="{repo_prefix}/{project}/{pr_id}",
    )
    assert config.generate_obs_repo_url(123, "http://obs", is_opensuse=False) == "http://obs/SUSE/Products/SLES/123"

    config_opensuse = TriggerConfig(
        distri="opensuse",
        flavor="Online",
        branch="openSUSE-Leap-15.5",
        repo_template="{repo_prefix}/{version}/{pr_id}",
    )
    assert config_opensuse.generate_obs_repo_url(123, "http://obs", is_opensuse=True) == "http://obs/15.5/123"


def test_trigger_config_get_build_project() -> None:
    """Test get_build_project replacement logic."""
    config = TriggerConfig(distri="sle", flavor="Online", project="SUSE/Products/SLES")
    assert config.get_build_project() == "SUSE_Products_SLES"


def test_trigger_config_get_branch_version() -> None:
    """Test get_branch_version branch matching and error cases."""
    config = TriggerConfig(distri="sle", flavor="Online", branch="openSUSE-Leap-15.5")
    assert config.get_branch_version() == "15.5"

    config_invalid = TriggerConfig(distri="sle", flavor="Online", branch="master")
    with pytest.raises(ValueError, match="Could not get version from master"):
        config_invalid.get_branch_version()


def test_trigger_config_get_os_template_setting() -> None:
    """Test get_os_template_setting resolution and failure."""
    config = TriggerConfig(
        distri="sle",
        flavor="Online",
        branch="openSUSE-Leap-15.5",
        settings={"OS_TEST_TEMPLATE": "template-{version}"},
    )
    assert config.get_os_template_setting() == "template-15.5"

    config_no_template = TriggerConfig(distri="sle", flavor="Online", settings={})
    with pytest.raises(ValueError, match="does not have expected OS_TEST_TEMPLATE"):
        config_no_template.get_os_template_setting()
