# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test Utils."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

import responses
from openqabot.types.types import Data
from openqabot.utils import (
    compare_submission_data,
    create_logger,
    get_yml_list,
    make_retry_session,
    normalize_results,
    walk,
)
from responses import registries

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_compare_submission_data() -> None:
    sub = Data(1, "type", 1, "flavor", "arch", "distri", "version", "build", "product")
    assert compare_submission_data(sub, {"BUILD": "build"}) is True
    assert compare_submission_data(sub, {"BUILD": "wrong"}) is False
    assert compare_submission_data(sub, {"FLAVOR": "flavor", "ARCH": "arch"}) is True
    assert compare_submission_data(sub, {"FLAVOR": "flavor", "ARCH": "wrong"}) is False
    assert compare_submission_data(sub, {"SOMETHING_ELSE": "foo"}) is True


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
def test_walk(data: list[Any] | dict[str, Any], result: list[Any] | dict[str, Any]) -> None:
    ret = walk(data)
    assert result == ret


@responses.activate(registry=registries.OrderedRegistry)
def test_make_retry_session(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.utils.number_of_retries", return_value=3)

    _ = responses.add(responses.GET, "http://host.some", status=503)
    _ = responses.add(responses.GET, "http://host.some", status=503)
    rsp3 = responses.add(responses.GET, "http://host.some", status=200)
    rsp4 = responses.add(responses.GET, "http://host.some", status=404)

    retry3 = make_retry_session(3, 2)
    req = retry3.get("http://host.some")
    assert req.status_code == 200
    assert rsp3.call_count == 1
    req = retry3.get("http://host.some")
    assert req.status_code == 404
    assert rsp4.call_count == 1


def test_get_yml_list_single_file_yml(tmp_path: Path) -> None:
    """Tests get_yml_list with single files.

    Creates a folder with a single .yml file.
    Calls get_yml_list with the path of the file
    The expected behavior is the function to return
    a single element list with the file Path.
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
    """Create a folder with 10 files in it, 5 has a valid extension."""
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


def test_create_logger_duplicate_handlers() -> None:

    name = "test_duplicate_logger"
    log = create_logger(name)
    assert len(log.handlers) == 1

    # second call should not add handler
    log2 = create_logger(name)
    assert log is log2
    assert len(log.handlers) == 1
