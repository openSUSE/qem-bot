# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader config."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from ruamel.yaml import YAML, YAMLError
from ruamel.yaml.constructor import ConstructorError, SafeConstructor
from ruamel.yaml.nodes import SequenceNode

from openqabot.loader.config import (
    ConcatSafeConstructor,
    concat_constructor,
    get_onearch,
    load_metadata,
    read_products,
)
from openqabot.types.types import Data

if TYPE_CHECKING:
    from collections.abc import Iterator

    from pytest_mock import MockerFixture

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


def _write_product(tmp_path: Path) -> None:
    (tmp_path / "prod.yml").write_text(
        "product: P\nsettings:\n  DISTRI: sle\n  VERSION: '1'\n"
        "incidents:\n  FLAVOR:\n    F:\n      archs:\n        - x86_64\n"
    )


@pytest.mark.parametrize(
    ("config_yml", "expected", "warns"),
    [
        pytest.param("excluded_packages:\n  - foo\n  - bar\n", ["foo", "bar"], False, id="list"),
        pytest.param("obs_url: https://api.example.com\n", None, False, id="key-absent"),
        pytest.param("excluded_packages: not-a-list\n", None, True, id="not-a-list"),
        pytest.param(None, None, False, id="missing-file"),
    ],
)
def test_load_metadata_central_blocklist(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    config_yml: str | None,
    expected: list[str] | None,
    *,
    warns: bool,
) -> None:
    """The central blocklist from config.yml is threaded into every worker; non-list values warn."""
    if config_yml is not None:
        (tmp_path / "config.yml").write_text(config_yml)
    _write_product(tmp_path)
    with caplog.at_level(logging.WARNING, logger="bot.loader.config"):
        workers = load_metadata(tmp_path, aggregate=True, submissions=False, extrasettings=set())
    assert workers[0].global_excluded_packages == expected
    assert ("Central blocklist ignored" in caplog.text) is warns


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


def test_concat_on_non_sequence_node_raises_clear_error() -> None:
    loader = YAML(typ="safe")
    loader.Constructor = ConcatSafeConstructor
    with pytest.raises(ConstructorError, match="expected a sequence node for !concat"):
        loader.load("result: !concat scalar")


def test_load_metadata_concat_simple_list() -> None:
    loader = YAML(typ="safe")
    loader.Constructor = ConcatSafeConstructor
    yaml_input = "result: !concat [ [a, b], [c, d] ]"
    data = loader.load(yaml_input)
    assert data["result"] == ["a", "b", "c", "d"]


def test_load_metadata_concat_mixed_list_scalar() -> None:
    loader = YAML(typ="safe")
    loader.Constructor = ConcatSafeConstructor
    yaml_input = "result: !concat [ [a, b], scalar, [c] ]"
    data = loader.load(yaml_input)
    assert data["result"] == ["a", "b", "scalar", "c"]


def test_load_metadata_concat_nested_and_anchors() -> None:
    loader = YAML(typ="safe")
    loader.Constructor = ConcatSafeConstructor
    # Use anchor and alias to force generator usage in ruamel.yaml
    yaml_input = "result: !concat [ &l [a, b], *l ]"
    data = loader.load(yaml_input)
    assert data["result"] == ["a", "b", "a", "b"]


def test_concat_constructor_container_unwrapping(mocker: MockerFixture) -> None:
    """Verify that concat_constructor correctly unwraps ruamel.yaml containers.

    In ruamel.yaml (when using typ='safe'), the construct_object method does not always
    return the final Python object immediately.
    For complex structures like sequences (lists) and mappings (dicts), it returns a generator.
    This design allows the library to handle self-referential anchors and aliases
    by yielding a placeholder before fully populating the object.
    This test ensures that concat_constructor correctly detects these generators and
    "unwraps" them to get the actual list or dictionary content.
    The test uses mock to simulate the internal state of ruamel.yaml without actually parsing a YAML string:
      1. `mock_constructor`: Mocks the SafeConstructor.
      2. `my_container()`: generator that yields a list: ["unwrapped"].
      3. `mock_node`: Mocks a SequenceNode (the !concat tag's content).
      4. `construct_object` setup: The mock is configured to return the my_container() generator when called.
    """
    mock_constructor = mocker.Mock()

    def my_container() -> Iterator[list[str]]:
        yield ["unwrapped"]

    # object with __next__
    mock_constructor.construct_object.return_value = my_container()

    mock_node = mocker.Mock(spec=SequenceNode)
    mock_node.value = [mocker.Mock()]

    it = concat_constructor(mock_constructor, mock_node)
    res = next(it)
    with pytest.raises(StopIteration):
        next(it)
    assert res == ["unwrapped"]


def test_concat_with_tuple_behavior() -> None:
    """Demonstrate why hasattr(obj, '__next__') is required over '__iter__'.

    Using __iter__ a tuple would be incorrectly 'unwrapped', resulting in
    only the first element being appended.
    """
    loader = YAML(typ="safe")
    loader.Constructor = ConcatSafeConstructor

    # We manually inject a tuple into the sequence to simulate a custom tag
    # or a complex ruamel.yaml state.
    class TupleConstructor(SafeConstructor):
        def construct_tuple(self, node: SequenceNode) -> tuple:
            return tuple(self.construct_sequence(node))

    loader.Constructor.add_constructor("!tuple", TupleConstructor.construct_tuple)

    # YAML input where !concat contains a tuple
    yaml_input = "result: !concat [ !tuple [a, b], [c] ]"
    data = loader.load(yaml_input)

    assert data["result"] == [("a", "b"), "c"]
