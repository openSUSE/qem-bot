# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import logging
from pathlib import Path

from openqabot.loader.config import get_onearch, load_metadata, read_products
from openqabot.types import Data

__root__ = Path(__file__).parent / "fixtures/config"


def test_singlearch():
    result = get_onearch(__root__ / "01_single.yml")
    assert result == {"package_one", "package_three", "package_two"}


def test_singlearch_error():
    result = get_onearch(__root__ / "single_non_exist.yml")
    assert result == set()


def test_load_metadata_aggregate(caplog):
    caplog.set_level(logging.DEBUG, logger="bot.loader.config")
    result = load_metadata(__root__, False, True, set())

    assert str(result[0]) == "<Aggregate product: SOME15SP3>"

    messages = sorted([m[-1] for m in caplog.record_tuples])
    assert "Skipping invalid config" in messages[3]
    assert "No 'test_issues' in BAD15SP3 config" in messages


def test_load_metadata_aggregate_file(caplog):
    caplog.set_level(logging.DEBUG, logger="bot.loader.config")
    file_path = Path(__file__).parent / "fixtures/config/05_normal.yml"
    result = load_metadata(file_path, False, True, set())

    assert "<Aggregate product: SOME15SP3>" in str(result[0])


def test_load_metadata_incidents(caplog):
    caplog.set_level(logging.DEBUG, logger="bot.loader.config")

    result = load_metadata(__root__, True, False, set())

    assert str(result[0]) == "<Incidents product: SOME15SP3>"

    messages = [m[-1] for m in caplog.record_tuples if m[-1].startswith("Skipping")]
    assert "Skipping invalid config" in messages[0]


def test_load_metadata_all(caplog):
    caplog.set_level(logging.DEBUG, logger="bot.loader.config")

    result = load_metadata(__root__, False, False, set())

    assert len(result) == 2
    assert str(result[0]) == "<Aggregate product: SOME15SP3>"
    assert str(result[1]) == "<Incidents product: SOME15SP3>"

    messages = sorted([m[-1] for m in caplog.record_tuples])
    assert "Skipping invalid config" in messages[3]
    assert "No 'test_issues' in BAD15SP3 config" in messages


def test_read_products(caplog):
    caplog.set_level(logging.DEBUG, logger="bot.loader.config")

    result = read_products(__root__)

    assert len(result) == 2
    assert (
        Data(
            incident=0,
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
    assert Data(
        incident=0,
        settings_id=0,
        flavor="Server-DVD-Updates",
        arch="aarch64",
        distri="bar",
        version="15-SP3",
        build="",
        product="SOME15SP3",
    )

    messages = [m[-1] for m in caplog.record_tuples]
    assert any(x.endswith("invalid format") for x in messages)
    assert any(x.endswith("empty config") for x in messages)
    assert any(x.endswith("with no 'aggregate' settings") for x in messages)
    assert any(x.endswith("with no 'DISTRI' settings") for x in messages)


def test_read_products_file(caplog):
    caplog.set_level(logging.DEBUG, logger="bot.loader.config")

    result = read_products(Path(__file__).parent / "fixtures/config/05_normal.yml")

    assert len(result) == 2
    assert (
        Data(
            incident=0,
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
    assert Data(
        incident=0,
        settings_id=0,
        flavor="Server-DVD-Updates",
        arch="aarch64",
        distri="bar",
        version="15-SP3",
        build="",
        product="SOME15SP3",
    )
