# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test RepoDiff."""

import json
from argparse import Namespace
from collections import defaultdict

import pytest
from lxml import etree  # ty: ignore[unresolved-import]
from pytest_mock import MockerFixture

from openqabot.config import settings
from openqabot.errors import NoResultsError
from openqabot.repodiff import Package, RepoDiff


@pytest.fixture
def diff(mocker: MockerFixture) -> RepoDiff:
    """Fixture for RepoDiff instance."""
    args = mocker.Mock()
    args.fake_data = False
    args.dump_data = False
    return RepoDiff(args)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            f"{settings.obs_download_url}/SUSE/Products/SL-Micro/6.2/x86_64/product/x86_64",
            f"{settings.obs_download_url}/SUSE/Products/SL-Micro/6.2/x86_64/product/x86_64/repodata/",
        ),
        (
            "https://example.com/repo/product/x86_64/",
            "https://example.com/repo/product/x86_64/repodata/",
        ),
    ],
)
def test_make_repodata_url_http(diff: RepoDiff, url: str, expected: str) -> None:
    assert diff.make_repodata_url(url) == expected


def test_repodiff_no_args(caplog: pytest.LogCaptureFixture) -> None:
    diff = RepoDiff(None)
    assert diff() == 1
    assert "RepoDiff called without arguments" in caplog.text


def test_repodiff(capsys: pytest.CaptureFixture[str]) -> None:
    RepoDiff(
        Namespace(
            dry=True,
            fake_data=True,
            repo_a=f"{settings.obs_download_url}/OBS:/PROJECT:/PUBLISH_product",
            repo_b=f"{settings.obs_download_url}/OBS:/PROJECT:/TEST_product",
        ),
    )()
    res = json.loads(capsys.readouterr().out)
    assert set(res.keys()) == {"aarch64", "ppc64le", "noarch"}


def test_repodiff_compression(capsys: pytest.CaptureFixture[str]) -> None:
    RepoDiff(
        Namespace(
            dry=True,
            fake_data=True,
            repo_a=f"{settings.obs_download_url}/OBS:/PROJECT:/PUBLISH_product_zst",
            repo_b=f"{settings.obs_download_url}/OBS:/PROJECT:/TEST_product_gz",
        ),
    )()
    res = json.loads(capsys.readouterr().out)
    assert set(res.keys()) == {"aarch64", "ppc64le", "noarch"}


@pytest.mark.parametrize(
    ("side_effect", "method", "expected_msg"),
    [
        (FileNotFoundError, "read_bytes", "Failed to read tests/fixtures/responses/name: File not found"),
        (json.JSONDecodeError("msg", "doc", 0), "read_bytes", "Failed to parse tests/fixtures/responses/name"),
    ],
)
def test_request_and_dump_fake_data_errors(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture, side_effect: Exception, method: str, expected_msg: str
) -> None:
    caplog.set_level("INFO")
    args = mocker.Mock()
    args.fake_data = True
    diff = RepoDiff(args)
    if isinstance(side_effect, json.JSONDecodeError):
        mocker.patch(f"openqabot.repodiff.Path.{method}", return_value=b"invalid json")
    else:
        mocker.patch(f"openqabot.repodiff.Path.{method}", side_effect=side_effect)
    res = diff.request_and_dump("http://url", "name", as_json=True)
    assert res is None
    assert expected_msg in caplog.text


def test_load_repodata_error(diff: RepoDiff, mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch.object(diff, "request_and_dump", return_value=None)
    res = diff.load_repodata("project")
    assert res is None
    assert "Could not load repo data for URL project" in caplog.text


def test_load_packages_empty(diff: RepoDiff, mocker: MockerFixture) -> None:
    mocker.patch.object(diff, "load_repodata", return_value=None)
    res = diff.load_packages("project")
    assert res == {}


def test_request_and_dump_exception(diff: RepoDiff, mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch("openqabot.repodiff.retried_requests.get", side_effect=Exception("foo"))
    res = diff.request_and_dump("http://url", "name")
    assert res is None
    assert "Failed to fetch or dump data from http://url" in caplog.text


def test_compute_diff_exception(diff: RepoDiff, mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch.object(diff, "load_packages", side_effect=Exception("foo"))
    res = diff.compute_diff("repo_a", "repo_b")
    assert res == (defaultdict(set), 0)
    assert "Repo diff computation failed for repositories repo_a and repo_b" in caplog.text


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


def test_request_and_dump_no_dump(diff: RepoDiff, mocker: MockerFixture) -> None:
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


@pytest.mark.parametrize(
    ("status_code", "reason", "expected_msg"),
    [
        (404, "Not Found", "Failed to fetch data from http://url: 404 Not Found"),
        (500, "Internal Server Error", "Failed to fetch data from http://url: 500 Internal Server Error"),
    ],
)
def test_request_and_dump_not_ok(
    diff: RepoDiff,
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    status_code: int,
    reason: str,
    expected_msg: str,
) -> None:
    caplog.set_level("INFO")
    mock_resp = mocker.Mock()
    mock_resp.ok = False
    mock_resp.status_code = status_code
    mock_resp.reason = reason
    mocker.patch("openqabot.repodiff.retried_requests.get", return_value=mock_resp)
    res = diff.request_and_dump("http://url", "name")
    assert res is None
    assert expected_msg in caplog.text


def test_find_primary_repodata_none(diff: RepoDiff, mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    # no primary repodata in rows
    mocker.patch.object(diff, "request_and_dump", return_value={"data": [{"name": "other.xml"}]})
    res = diff.load_repodata("project")
    assert res is None
    assert "Repository metadata not found" in caplog.text


def test_load_repodata_request_failed(diff: RepoDiff, mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    # repo_data_listing found, but subsequent request fails
    mocker.patch.object(diff, "request_and_dump", side_effect=[{"data": [{"name": "foo-primary.xml"}]}, None])
    res = diff.load_repodata("project")
    assert res is None
    assert "Repository metadata could not be fetched" in caplog.text


def test_load_packages_not_rpm(diff: RepoDiff, mocker: MockerFixture) -> None:
    # mock repo_data with non-rpm package
    xml = etree.fromstring(
        '<metadata xmlns="http://linux.duke.edu/metadata/common">'
        '<package type="other"><name>n</name></package></metadata>'
    )
    mocker.patch.object(diff, "load_repodata", return_value=xml)
    res = diff.load_packages("project")
    assert res == {}


def test_get_staged_update_name_success(diff: RepoDiff, mocker: MockerFixture) -> None:
    """Test get_staged_update_name happy path."""
    pkg1 = mocker.Mock()
    pkg1.name = "pkg-b"
    pkg2 = mocker.Mock()
    pkg2.name = "pkg-a"
    mocker.patch.object(diff, "load_packages", return_value={"x86_64": {pkg1, pkg2}})
    assert diff.get_staged_update_name("http://repo") == "pkg-a"


def test_get_staged_update_name_empty(diff: RepoDiff, mocker: MockerFixture) -> None:
    """Test get_staged_update_name raises NoResultsError when no packages are found."""
    mocker.patch.object(diff, "load_packages", return_value={"x86_64": set()})
    with pytest.raises(NoResultsError, match="No packages detected"):
        diff.get_staged_update_name("http://repo")


@pytest.mark.parametrize(
    ("repo_data", "expected_pkgs"),
    [
        (
            (
                b'<metadata xmlns="http://linux.duke.edu/metadata/common">'
                b'<package type="rpm">'
                b"<name>test-package</name>"
                b'<version epoch="0" ver="1.0" rel="1"/>'
                b"<arch>x86_64</arch>"
                b"</package></metadata>"
            ),
            {"x86_64": {Package("test-package", "0", "1.0", "1", "x86_64")}},
        ),
        (
            (
                b'<metadata xmlns="http://linux.duke.edu/metadata/common">'
                b'<package type="other1"><name>other1</name></package>'
                b'<package type="other2"><name>other2</name></package>'
                b'<package type="rpm">'
                b"<name>rpm-package</name>"
                b'<version epoch="0" ver="2.0" rel="1"/>'
                b"<arch>aarch64</arch>"
                b"</package></metadata>"
            ),
            {"aarch64": {Package("rpm-package", "0", "2.0", "1", "aarch64")}},
        ),
        (
            (
                b'<metadata xmlns="http://linux.duke.edu/metadata/common">'
                b'<package type="rpm"><name>incomplete</name></package></metadata>'
            ),
            {},
        ),
        (
            b'<package xmlns="http://linux.duke.edu/metadata/common" type="other"><name>other-package</name></package>',
            {},
        ),
        (
            (
                b'<package xmlns="http://linux.duke.edu/metadata/common" type="rpm">'
                b"<name>rpm-package</name>"
                b'<version epoch="0" ver="2.0" rel="1"/>'
                b"<arch>aarch64</arch></package>"
            ),
            {"aarch64": {Package("rpm-package", "0", "2.0", "1", "aarch64")}},
        ),
        (
            etree.fromstring(
                '<metadata xmlns="http://linux.duke.edu/metadata/common">'
                '<package type="rpm">'
                "<name>element-package</name>"
                '<version epoch="0" ver="3.0" rel="1"/>'
                "<arch>x86_64</arch>"
                "</package></metadata>"
            ),
            {"x86_64": {Package("element-package", "0", "3.0", "1", "x86_64")}},
        ),
        (
            etree.fromstring(
                '<metadata xmlns="http://linux.duke.edu/metadata/common">'
                '<package type="rpm">'
                "<name>incomplete-package</name>"
                "</package></metadata>"
            ),
            {},
        ),
    ],
    ids=[
        "stream_valid_rpm",
        "stream_non_rpm_and_clear",
        "stream_missing_fields",
        "stream_root_non_rpm_parent_none",
        "stream_root_rpm_parent_none",
        "fallback_valid_element",
        "fallback_missing_fields",
    ],
)
def test_load_packages_parameterized(
    diff: RepoDiff,
    mocker: MockerFixture,
    repo_data: bytes | etree._Element,
    expected_pkgs: dict[str, set[Package]],
) -> None:
    """Test load_packages parsing logic across various data types and layouts."""
    mocker.patch.object(diff, "load_repodata", return_value=repo_data)
    res = diff.load_packages("project")
    assert res == expected_pkgs


def test_load_packages_stream_exception(
    diff: RepoDiff, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """Test stream parser exceptions handling."""
    mocker.patch("openqabot.repodiff.etree.iterparse", side_effect=ValueError("corrupted XML"))
    mocker.patch.object(diff, "load_repodata", return_value=b"corrupted bytes")
    res = diff.load_packages("project")
    assert res == {}
    assert "Failed to parse repo data stream" in caplog.text
