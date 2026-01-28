# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import logging
from argparse import Namespace
from pathlib import Path
from unittest.mock import ANY

import pytest
from pytest_mock import MockerFixture

from openqabot.loader.incrementconfig import IncrementConfig


def test_from_config_file_invalid_yaml(mocker: MockerFixture, tmp_path: Path) -> None:
    invalid_yaml_file = tmp_path / "invalid.yml"
    invalid_yaml_file.write_text("key: value:")

    mock_logger = mocker.patch("openqabot.loader.incrementconfig.log")
    configs = list(IncrementConfig.from_config_file(invalid_yaml_file))

    assert configs == []
    mock_logger.info.assert_any_call("Increment configuration skipped: Could not load '%s': %s", invalid_yaml_file, ANY)


def test_config_parsing(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.increment_config")
    path = Path("tests/fixtures/config-increment-approver")
    configs = [*IncrementConfig.from_config_path(path)]
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
    assert configs[0].diff_project() == "FOO:PUBLISH/product"
    assert configs[1].distri == "bar"
    assert configs[1].version == "42"
    assert configs[1].flavor == "Test-Increments"
    assert configs[1].project_base == ""  # noqa: PLC1901
    assert configs[1].build_project() == "ToTest"
    assert configs[1].diff_project() == "none"

    path = Path("tests/fixtures/config")
    caplog.set_level(logging.DEBUG, logger="bot.increment_approver")
    configs = IncrementConfig.from_config_path(path)
    assert [*configs] == []
    assert "File 'tests/fixtures/config/01_single.yml' skipped: Not a valid increment configuration" in caplog.text
    assert "Loading increment configuration from 'tests/fixtures/config/03_no_tes" in caplog.text


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


def test_config_parsing_from_args_with_path() -> None:
    path = Path("tests/fixtures/config-increment-approver")
    config = IncrementConfig.from_args(
        Namespace(increment_config=path, distri="sle", version="16.0", flavor="Online-Increments")
    )
    assert len(config) == 2
    assert config[0].distri == "foo"
    assert config[1].distri == "bar"
