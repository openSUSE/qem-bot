# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Union

import pytest

import responses
from openqabot.utils import get_yml_list, normalize_results, retry3, walk

log = logging.getLogger(__name__)
# responses versions older than
# https://github.com/getsentry/responses/releases/tag/0.17.0
# do not have "registries" so we need to skip on older versions
has_registries = False
try:
    from responses import registries

    has_registries = True
except ImportError as e:
    import logging

    log.info("%s: Likely older python version", e)


def test_normalize_results() -> None:
    assert normalize_results("none") == "waiting"
    assert normalize_results("passed") == "passed"
    assert normalize_results("failed") == "failed"
    assert normalize_results("something") == "failed"
    assert normalize_results("softfailed") == "passed"
    for result in (
        "timeout_exceeded",
        "incomplete",
        "obsoleted",
        "parallel_failed",
        "skipped",
        "parallel_restarted",
        "user_cancelled",
        "user_restarted",
    ):
        assert normalize_results(result) == "stopped"


@pytest.mark.parametrize(
    ("data", "result"),
    [
        ([], []),
        ({}, {}),
        (
            {
                "d": {
                    "i": {
                        "edges": [
                            {
                                "node": {
                                    "rS": {"edges": []},
                                    "p": {"edges": [{"node": {"name": "ra"}}]},
                                    "r": {
                                        "edges": [
                                            {"node": {"name": "12:x86_64"}},
                                            {"node": {"name": "12:Update"}},
                                            {"node": {"name": "12:s390x"}},
                                        ],
                                    },
                                    "c": {"edges": []},
                                    "cM": None,
                                    "cQ": None,
                                },
                            },
                        ],
                    },
                },
            },
            {
                "d": {
                    "i": [
                        {
                            "cM": None,
                            "cQ": None,
                            "c": [],
                            "p": [{"name": "ra"}],
                            "r": [
                                {"name": "12:x86_64"},
                                {"name": "12:Update"},
                                {"name": "12:s390x"},
                            ],
                            "rS": [],
                        },
                    ],
                },
            },
        ),
    ],
)
def test_walk(data: Union[List[Any], Dict[str, Any]], result: Union[List[Any], Dict[str, Any]]) -> None:
    ret = walk(data)
    assert result == ret


if has_registries:

    @responses.activate(registry=registries.OrderedRegistry)
    def test_retry3() -> None:
        _ = responses.add(responses.GET, "http://host.some", status=503)
        _ = responses.add(responses.GET, "http://host.some", status=503)
        rsp3 = responses.add(responses.GET, "http://host.some", status=200)
        rsp4 = responses.add(responses.GET, "http://host.some", status=404)

        req = retry3.get("http://host.some")
        assert req.status_code == 200
        assert rsp3.call_count == 1
        req = retry3.get("http://host.some")
        assert req.status_code == 404
        assert rsp4.call_count == 1


def test_get_yml_list_single_file_yml(tmp_path: Path) -> None:
    """Create a folder with a single .yml file
    Call the function with the path of the file
    The expected behavior is the function to return
    a single element list with the file Path
    """
    for ext in ("yml", "yaml"):
        d = tmp_path / f"it_is_a_folder_for_{ext}"
        d.mkdir()
        filename = f"hello.{ext}"
        p = d / filename
        p.write_text("")
        # here call the function with the file path
        res = get_yml_list(Path(p))
        assert len(res) == 1
        assert filename in res[0].name


def test_get_yml_list_folder_with_single_file_yml(tmp_path: Path) -> None:
    d = tmp_path / "it_is_a_folder"
    d.mkdir()
    p = d / "hello.yml"
    p.write_text("")
    # here call the function with the folder and not with file like in previous tests
    res = get_yml_list(Path(d))
    assert len(res) == 1
    assert "hello.yml" in res[0].name


def test_get_yml_list_folder_with_multiple_files(tmp_path: Path) -> None:
    """Create a folder with 10 files in it, 5 has a valid extension"""
    d = tmp_path / "it_is_a_folder"
    d.mkdir()
    for ext in ("txt", "yml", "yaml"):
        for _ in range(5):
            p = d / f"hello{_}.{ext}"
            p.write_text(f"Content {_}")
    # here call the function with the folder
    res = get_yml_list(Path(d))
    # only 5 yml + 5 yaml files over 15 total files
    assert len(res) == 10
