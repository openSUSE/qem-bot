# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import json
from typing import NamedTuple

import pytest
from pytest_mock import MockerFixture

from openqabot.repodiff import RepoDiff


class Namespace(NamedTuple):
    dry: bool
    fake_data: bool
    repo_a: str
    repo_b: str


def test_repodiff(capsys: pytest.CaptureFixture[str]) -> None:
    RepoDiff(
        Namespace(
            dry=True,
            fake_data=True,
            repo_a="OBS:PROJECT:PUBLISH_product",
            repo_b="OBS:PROJECT:TEST_product",
        ),
    )()
    res = json.loads(capsys.readouterr().out)
    assert set(res.keys()) == {"aarch64", "ppc64le", "noarch"}


def test_repodiff_compression(capsys: pytest.CaptureFixture[str]) -> None:
    RepoDiff(
        Namespace(
            dry=True,
            fake_data=True,
            repo_a="OBS:PROJECT:PUBLISH_product_zst",
            repo_b="OBS:PROJECT:TEST_product_gz",
        ),
    )()
    res = json.loads(capsys.readouterr().out)
    assert set(res.keys()) == {"aarch64", "ppc64le", "noarch"}


def test_request_and_dump_not_found(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    from openqabot.repodiff import RepoDiff

    args = mocker.Mock()
    args.fake_data = True
    diff = RepoDiff(args)
    mocker.patch("openqabot.repodiff.Path.read_bytes", side_effect=FileNotFoundError)
    res = diff._request_and_dump("http://url", "name")  # noqa: SLF001
    assert res is None
    assert "Failed to read responses/name" in caplog.text


def test_request_and_dump_invalid_json(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    from openqabot.repodiff import RepoDiff

    args = mocker.Mock()
    args.fake_data = True
    diff = RepoDiff(args)
    mocker.patch("openqabot.repodiff.Path.read_text", return_value="invalid json")
    res = diff._request_and_dump("http://url", "name", as_json=True)  # noqa: SLF001
    assert res is None
    assert "Failed to parse responses/name" in caplog.text


def test_load_repodata_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    from openqabot.repodiff import RepoDiff

    args = mocker.Mock()
    diff = RepoDiff(args)
    mocker.patch.object(diff, "_request_and_dump", return_value=None)
    res = diff._load_repodata("project")  # noqa: SLF001
    assert res is None
    assert "Could not load repo data for project project" in caplog.text


def test_load_packages_empty(mocker: MockerFixture) -> None:
    from openqabot.repodiff import RepoDiff

    args = mocker.Mock()
    diff = RepoDiff(args)
    mocker.patch.object(diff, "_load_repodata", return_value=None)
    res = diff._load_packages("project")  # noqa: SLF001
    assert res == {}


def test_load_packages_invalid_data(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    from openqabot.repodiff import RepoDiff

    args = mocker.Mock()
    diff = RepoDiff(args)
    # Return a dict instead of etree.Element
    mocker.patch.object(diff, "_load_repodata", return_value={"invalid": "data"})
    res = diff._load_packages("project")  # noqa: SLF001
    assert res == {}
    assert "Could not load repo data for project project" in caplog.text


def test_compute_diff_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    from collections import defaultdict

    from openqabot.repodiff import RepoDiff

    args = mocker.Mock()
    diff = RepoDiff(args)
    mocker.patch.object(diff, "_load_packages", side_effect=Exception("foo"))
    res = diff.compute_diff("repo_a", "repo_b")
    assert res == (defaultdict(set), 0)
    assert "Repo diff computation failed for projects repo_a and repo_b" in caplog.text
