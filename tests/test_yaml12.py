# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loading YAML 1.2 core documents with merge keys."""

import pytest

from openqabot import yaml12


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("a: 1\n", {"a": 1}),
        ("b: &b {k: v}\nm:\n  <<: *b\n  n: 2\n", {"b": {"k": "v"}, "m": {"k": "v", "n": 2}}),
        (
            "a: &a {k: 1, only_a: 1}\nb: &b {k: 2, only_b: 2}\nm:\n  <<: [*a, *b]\n",
            {"a": {"k": 1, "only_a": 1}, "b": {"k": 2, "only_b": 2}, "m": {"k": 1, "only_b": 2, "only_a": 1}},
        ),
        ("b: &b {k: v}\nm:\n  <<: *b\n  k: own\n", {"b": {"k": "v"}, "m": {"k": "own"}}),
        (
            "base: &base {k: base, x: 1}\nmid: &mid {<<: *base, k: mid}\nm:\n  <<: *mid\n",
            {"base": {"k": "base", "x": 1}, "mid": {"k": "mid", "x": 1}, "m": {"k": "mid", "x": 1}},
        ),
        (
            "outer:\n  base: &base {k: v, x: 1}\nm:\n  <<: *base\n  n: 2\n",
            {"outer": {"base": {"k": "v", "x": 1}}, "m": {"k": "v", "x": 1, "n": 2}},
        ),
        (
            "packagesets: [{base: &base {packages: [a, b]}}, {<<: *base, name: x}]\n",
            {"packagesets": [{"base": {"packages": ["a", "b"]}}, {"packages": ["a", "b"], "name": "x"}]},
        ),
        ("b: &b {}\nm:\n  <<: *b\n  n: 2\n", {"b": {}, "m": {"n": 2}}),
        ("m:\n  <<: []\n  n: 2\n", {"m": {"n": 2}}),
        ("a: &a {<<: *a}\n", {"a": {}}),
        ("a: &a {<<: *a, k: 1}\n", {"a": {"k": 1}}),
        ("a: &a {<<: [*a]}\n", {"a": {}}),
        (
            "v: [yes, no, on, off, 10:20, 1_0, 010, 0o10, 2024-01-01]\n",
            {"v": ["yes", "no", "on", "off", "10:20", "1_0", 10, 8, "2024-01-01"]},
        ),
    ],
    ids=[
        "plain",
        "merge_mapping",
        "merge_sequence",
        "explicit_key_overrides_merge",
        "nested_merge",
        "anchor_nested_deeper",
        "merge_from_earlier_sequence_item",
        "empty_merge_anchor",
        "empty_merge_sequence",
        "self_merge",
        "self_merge_own_mapping",
        "self_merge_sequence",
        "core_scalars",
    ],
)
def test_load(content: str, expected: dict) -> None:
    assert yaml12.load(content) == expected


@pytest.mark.parametrize(
    "content",
    [
        "a: 1\na: 2\n",
        "m:\n  <<: 42\n",
        "m:\n  <<: [{a: 1}, scalar]\n",
        "m:\n  <<: {k: 1, k: 2}\n",
        "m:\n  <<: [{k: 1, k: 2}]\n",
        "!!map not_a_mapping\n",
    ],
    ids=[
        "duplicate_key",
        "merge_value_not_a_mapping",
        "merge_sequence_item_not_a_mapping",
        "merge_source_duplicate",
        "merge_sequence_item_duplicate",
        "wrong_node_type",
    ],
)
def test_load_rejects(content: str) -> None:
    with pytest.raises(yaml12.Yaml12Error):
        yaml12.load(content)
