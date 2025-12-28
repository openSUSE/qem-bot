# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from ruamel.yaml import YAMLError

from openqabot.loader.config import load_metadata, read_products


def test_load_one_metadata_missing_settings(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.INFO)
    # Mock get_yml_list to return one path
    mocker.patch("openqabot.loader.config.get_yml_list", return_value=[Path("fake.yml")])
    # Mock YAML.load to return data without settings
    mock_yaml = mocker.patch("openqabot.loader.config.YAML")
    mock_yaml.return_value.load.return_value = {"product": "something"}

    result = load_metadata(Path(), aggregate=False, incidents=False, extrasettings=set())
    assert result == []
    assert "Configuration skipped: Missing settings in 'fake.yml'" in caplog.text


def test_read_products_yaml_error(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.ERROR)
    # Mock get_yml_list to return one path
    mocker.patch("openqabot.loader.config.get_yml_list", return_value=[Path("invalid.yml")])
    # Mock YAML.load to raise YAMLError
    mock_yaml = mocker.patch("openqabot.loader.config.YAML")
    mock_yaml.return_value.load.side_effect = YAMLError("Simulated error")

    result = read_products(Path())
    assert result == []
    assert "YAML load failed: File invalid.yml" in caplog.text
