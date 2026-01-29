# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import json
from argparse import Namespace
from collections import defaultdict

import pytest
from lxml import etree  # type: ignore[unresolved-import]
from pytest_mock import MockerFixture

from openqabot.repodiff import RepoDiff


def test_repodiff_no_args(caplog: pytest.LogCaptureFixture) -> None:
    diff = RepoDiff(None)
    assert diff() == 1
    assert "RepoDiff called without arguments" in caplog.text


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
    args = mocker.Mock()
    args.fake_data = True
    diff = RepoDiff(args)
    mocker.patch("openqabot.repodiff.Path.read_bytes", side_effect=FileNotFoundError)
    res = diff.request_and_dump("http://url", "name")
    assert res is None
    assert "Failed to read responses/name" in caplog.text


def test_request_and_dump_invalid_json(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    args = mocker.Mock()
    args.fake_data = True
    diff = RepoDiff(args)
    mocker.patch("openqabot.repodiff.Path.read_text", return_value="invalid json")
    res = diff.request_and_dump("http://url", "name", as_json=True)
    assert res is None
    assert "Failed to parse responses/name" in caplog.text


def test_load_repodata_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    args = mocker.Mock()
    diff = RepoDiff(args)
    mocker.patch.object(diff, "request_and_dump", return_value=None)
    res = diff.load_repodata("project")
    assert res is None
    assert "Could not load repo data for project project" in caplog.text


def test_load_packages_empty(mocker: MockerFixture) -> None:
    args = mocker.Mock()
    diff = RepoDiff(args)
    mocker.patch.object(diff, "load_repodata", return_value=None)
    res = diff.load_packages("project")
    assert res == {}


def test_load_packages_invalid_data(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    args = mocker.Mock()
    diff = RepoDiff(args)
    # Return a dict instead of etree.Element
    mocker.patch.object(diff, "load_repodata", return_value={"invalid": "data"})
    res = diff.load_packages("project")
    assert res == {}
    assert "Could not load repo data for project project" in caplog.text


def test_request_and_dump_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    args = mocker.Mock()
    args.fake_data = False
    args.dump_data = False
    diff = RepoDiff(args)
    mocker.patch("openqabot.repodiff.retried_requests.get", side_effect=Exception("foo"))
    res = diff.request_and_dump("http://url", "name")
    assert res is None
    assert "Failed to fetch or dump data from http://url" in caplog.text


def test_compute_diff_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    args = mocker.Mock()
    diff = RepoDiff(args)
    mocker.patch.object(diff, "load_packages", side_effect=Exception("foo"))
    res = diff.compute_diff("repo_a", "repo_b")
    assert res == (defaultdict(set), 0)
    assert "Repo diff computation failed for projects repo_a and repo_b" in caplog.text


def test_request_and_dump_dump_data(mocker: MockerFixture) -> None:
    args = mocker.Mock()
    args.fake_data = False
    args.dump_data = True
    diff = RepoDiff(args)
    mock_resp = mocker.Mock()
    mock_resp.content = b"content"
    mock_resp.status_code = 200
    mocker.patch("openqabot.repodiff.retried_requests.get", return_value=mock_resp)
    mock_write = mocker.patch("openqabot.repodiff.Path.write_bytes")
    res = diff.request_and_dump("http://url", "name")
    assert res == b"content"
    mock_write.assert_called_once_with(b"content")


def test_request_and_dump_no_dump(mocker: MockerFixture) -> None:
    args = mocker.Mock()
    args.fake_data = False
    args.dump_data = False
    diff = RepoDiff(args)
    mock_resp = mocker.Mock()
    mock_resp.content = b"content"
    mock_resp.status_code = 200
    mocker.patch("openqabot.repodiff.retried_requests.get", return_value=mock_resp)
    mock_write = mocker.patch("openqabot.repodiff.Path.write_bytes")
    res = diff.request_and_dump("http://url", "name")
    assert res == b"content"
    assert not mock_write.called


def test_repodiff_exit(mocker: MockerFixture) -> None:
    diff = RepoDiff(
        Namespace(
            dry=True,
            fake_data=True,
            repo_a="NONEXISTENT",
            repo_b="NONEXISTENT",
        ),
    )
    mocker.patch.object(diff, "compute_diff", side_effect=FileNotFoundError("foo"))
    with pytest.raises(SystemExit):
        diff()


def test_find_primary_repodata_none(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    args = mocker.Mock()
    diff = RepoDiff(args)
    # no primary repodata in rows
    mocker.patch.object(diff, "request_and_dump", return_value={"data": [{"name": "other.xml"}]})
    res = diff.load_repodata("project")
    assert res is None
    assert "Repository metadata not found" in caplog.text


def test_load_repodata_request_failed(mocker: MockerFixture) -> None:
    args = mocker.Mock()
    diff = RepoDiff(args)
    # repo_data_listing found, but subsequent request fails
    mocker.patch.object(diff, "request_and_dump", side_effect=[{"data": [{"name": "foo-primary.xml"}]}, None])
    res = diff.load_repodata("project")
    assert res is None


def test_load_packages_not_rpm(mocker: MockerFixture) -> None:
    args = mocker.Mock()
    diff = RepoDiff(args)
    # mock repo_data with non-rpm package
    xml = etree.fromstring(
        '<metadata xmlns="http://linux.duke.edu/metadata/common">'
        '<package type="other"><name>n</name></package></metadata>'
    )
    mocker.patch.object(diff, "load_repodata", return_value=xml)
    res = diff.load_packages("project")
    assert res == {}
