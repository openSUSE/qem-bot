# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader increment config."""

import logging
from argparse import Namespace
from pathlib import Path

import pytest

from openqabot.loader.config import get_configs_from_path
from openqabot.loader.incrementconfig import IncrementConfig
from openqabot.types.increment import BuildInfo


def test_config_parsing(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.increment_config")
    path = Path("tests/fixtures/config-increment-approver")
    configs = get_configs_from_path(path, "product_increments", IncrementConfig.from_config_entry)
    assert configs[0].distri == "foo"
    assert configs[0].version == "any"
    assert configs[0].flavor == "any"
    assert configs[0].project_base == "FOO"
    assert configs[0].build_project_suffix == "TEST"
    assert configs[0].diff_project_suffix == "PUBLISH/product"
    assert configs[0].build_listing_sub_path == "product"
    assert configs[0].build_regex == "some.*regex"
    assert configs[0].product_regex == "^Foo.*"
    assert configs[0].archs == {"x86_64", "aarch64", "ppc64le"}
    assert configs[0].packages == ["kernel-source", "kernel-azure"]
    assert configs[0].build_project() == "FOO:TEST"
    assert configs[0].diff_project_url() == "http://download.suse.de/ibs/FOO:/PUBLISH/product"
    assert configs[1].distri == "bar"
    assert configs[1].version == "42"
    assert configs[1].flavor == "Test-Increments"
    assert configs[1].project_base == ""  # ruff: ignore[compare-to-empty-string]
    assert configs[1].build_project() == "ToTest"
    assert configs[1].diff_project_url() == "http://download.suse.de/ibs/none"

    path = Path("tests/fixtures/config")
    caplog.set_level(logging.DEBUG, logger="bot.loader.config")
    configs = get_configs_from_path(path, "product_increments", IncrementConfig.from_config_entry)
    assert configs == []
    assert (
        "File 'tests/fixtures/config/01_single.yml' skipped: Not a valid product_increments's configuration"
        in caplog.text
    )
    assert (
        "Loading product_increments's configuration from 'tests/fixtures/config/03_no_test_issues.yml'" in caplog.text
    )


def test_config_parsing_from_args() -> None:
    config = IncrementConfig.from_args(
        Namespace(increment_config=None, distri="sle", version="16.0", flavor="Online-Increments")
    )
    assert len(config) == 1
    assert config[0].distri == "sle"
    assert config[0].version == "16.0"
    assert config[0].flavor == "Online-Increments"
    assert config[0].packages == []
    assert config[0].archs == set()
    assert config[0].settings == {}


@pytest.mark.parametrize(("config_index", "expected_distri"), [(0, "foo"), (1, "bar")])
def test_config_parsing_from_args_with_path(config_index: int, expected_distri: str) -> None:
    path = Path("tests/fixtures/config-increment-approver")
    configs = IncrementConfig.from_args(
        Namespace(increment_config=path, distri="sle", version="16.0", flavor="Online-Increments")
    )
    assert len(configs) == 2
    config = configs[config_index]
    assert config.distri == expected_distri
    additional_settings = {
        "ADDITIONAL_SETTING1": "present",
        "ADDITIONAL_SETTING2": "also here",
    }
    assert additional_settings.items() <= config.settings.items()


def test_config_parsing_from_args_with_auto_discovery() -> None:
    path = Path("tests/fixtures/config-increment-approver")
    configs = IncrementConfig.from_args(
        Namespace(increment_config=None, configs=path, distri="sle", version="16.0", flavor="Online-Increments")
    )
    assert len(configs) == 2
    assert configs[0].distri == "foo"
    assert configs[1].distri == "bar"


def test_config_parsing_from_args_fallback_to_cli() -> None:
    path = Path("tests/fixtures/config")
    configs = IncrementConfig.from_args(
        Namespace(increment_config=None, configs=path, distri="sle", version="16.0", flavor="Online-Increments")
    )
    assert len(configs) == 1
    assert configs[0].distri == "sle"


def test_concat_project() -> None:
    config = IncrementConfig(
        distri="sle",
        version="16.0",
        flavor="Online-Increments",
        project_base="BASE",
        build_project_suffix="",
    )
    assert config.build_project() == "BASE"
    config.project_base = ""
    assert config.build_project() == ""  # ruff: ignore[compare-to-empty-string]
    config.project_base = "BASE"
    config.build_project_suffix = "SUFFIX"
    assert config.build_project() == "BASE:SUFFIX"


def test_config_parsing_reference_repos() -> None:
    entry = {
        "distri": "sle",
        "project_base": "BASE",
        "build_project_suffix": "BUILD",
        "diff_project_suffix": "DIFF",
        "build_listing_sub_path": "path",
        "build_regex": "regex",
        "product_regex": "pregex",
        "reference_repos": {"SLES": "REPO1", "SLES-SAP": "REPO2"},
    }
    config = IncrementConfig.from_config_entry(entry)
    assert config.reference_repos == {"SLES": "REPO1", "SLES-SAP": "REPO2"}


def test_accepts_build_info_regex() -> None:
    config = IncrementConfig(
        distri="sle",
        version="any",
        flavor="Online-Increments",
        arch="x86_64",
        product_regex="^SLES",
        version_regex="^15.5",
    )

    # Matches everything
    assert config.accepts_build_info(BuildInfo("sle", "SLES", "15.5", "Online-Increments", "x86_64", "1"))

    # Mismatch product
    assert not config.accepts_build_info(BuildInfo("sle", "SLED", "15.5", "Online-Increments", "x86_64", "1"))

    # Mismatch version
    assert not config.accepts_build_info(BuildInfo("sle", "SLES", "15.4", "Online-Increments", "x86_64", "1"))
