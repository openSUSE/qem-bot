# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader config."""

import logging
from pathlib import Path

import pytest
from pytest_mock import MockerFixture
from ruamel.yaml import YAMLError

from openqabot.loader.config import get_onearch, load_metadata, read_products
from openqabot.types.submissions import Submissions
from openqabot.types.types import Data

__root__ = Path(__file__).parent / "fixtures/config"


def test_get_onearch() -> None:
    """Try to read the onearch file."""
    res = get_onearch(__root__ / "01_single.yml")
    assert res == {"package_one", "package_two", "package_three"}


def test_get_onearch_not_found() -> None:
    """Try to read a non-existing onearch file."""
    res = get_onearch(__root__ / "non-existing")
    assert res == set()


def test_load_metadata_aggregate_all_files_in_folder(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.config")
    result = load_metadata(__root__, aggregate=False, submissions=True, extrasettings=set())

    assert len(result) == 1
    assert str(result[0]) == "<Aggregate product: SOME15SP3>"


def test_load_metadata_aggregate_file(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.config")
    file_path = __root__ / "05_normal.yml"
    result = load_metadata(file_path, aggregate=False, submissions=True, extrasettings=set())

    assert len(result) == 1
    assert str(result[0]) == "<Aggregate product: SOME15SP3>"


def test_load_metadata_incidents_all_files_in_folder(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.config")

    result = load_metadata(__root__, aggregate=True, submissions=False, extrasettings=set())

    assert len(result) == 1
    assert str(result[0]) == "<Submissions product: SOME15SP3>"


def test_load_metadata_all(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.config")

    result = load_metadata(__root__, aggregate=False, submissions=False, extrasettings=set())

    assert len(result) == 2
    # The order depends on how YAML data keys are iterated.
    # In 05_normal.yml, 'aggregate' comes before 'incidents'.
    assert str(result[0]) == "<Aggregate product: SOME15SP3>"
    assert str(result[1]) == "<Submissions product: SOME15SP3>"


def test_load_metadata_exclude_all() -> None:
    result = load_metadata(__root__, aggregate=True, submissions=True, extrasettings=set())
    assert len(result) == 0


def test_load_metadata_concat() -> None:
    result = load_metadata(
        Path(__file__).parent / "fixtures/config-concat", aggregate=False, submissions=False, extrasettings=set()
    )
    assert len(result) == 2
    assert isinstance(result[1], Submissions)
    assert len(result[1].flavors["Server-DVD-Incidents-Kernel"]["packages"]) == 3


def test_read_products(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.config")

    result = read_products(__root__)

    assert len(result) == 2
    assert (
        Data(
            submission=0,
            submission_type="aggregate",
            settings_id=0,
            flavor="Server-DVD-Updates",
            arch="x86_64",
            distri="bar",
            version="15-SP3",
            build="",
            product="SOME15SP3",
        )
        in result
    )
    assert (
        Data(
            submission=0,
            submission_type="aggregate",
            settings_id=0,
            flavor="Server-DVD-Updates",
            arch="aarch64",
            distri="bar",
            version="15-SP3",
            build="",
            product="SOME15SP3",
        )
        in result
    )


def test_read_products_file(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.config")

    result = read_products(__root__ / "05_normal.yml")

    assert len(result) == 2
    assert (
        Data(
            submission=0,
            submission_type="aggregate",
            settings_id=0,
            flavor="Server-DVD-Updates",
            arch="x86_64",
            distri="bar",
            version="15-SP3",
            build="",
            product="SOME15SP3",
        )
        in result
    )
    assert (
        Data(
            submission=0,
            submission_type="aggregate",
            settings_id=0,
            flavor="Server-DVD-Updates",
            arch="aarch64",
            distri="bar",
            version="15-SP3",
            build="",
            product="SOME15SP3",
        )
        in result
    )


def test_invalid_yaml_file_is_skipped(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mock_yaml_class = mocker.patch("openqabot.loader.config.YAML")
    mock_yaml_class.return_value.load.side_effect = YAMLError("Simulated YAML error")
    file_path = __root__ / "simulated_invalid.yml"
    load_metadata(file_path, aggregate=False, submissions=True, extrasettings=set())
    assert "YAML load failed" in caplog.text


def test_load_one_metadata_missing_settings(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.INFO)
    # Mock get_yml_list to return one path
    mocker.patch("openqabot.loader.config.get_yml_list", return_value=[Path("fake.yml")])
    # Mock YAML.load to return data without settings
    mock_yaml = mocker.patch("openqabot.loader.config.YAML")
    mock_yaml.return_value.load.return_value = {"product": "something"}

    result = load_metadata(Path(), aggregate=False, submissions=False, extrasettings=set())
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
