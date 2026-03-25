# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test source report."""

import logging
from collections import defaultdict
from email.message import Message
from unittest.mock import MagicMock
from urllib.error import HTTPError

import pytest
from lxml import etree  # ty: ignore[unresolved-import]
from pytest_mock import MockerFixture

from openqabot.loader.sourcereport import find_source_reports, load_packages_from_source_report, parse_source_report
from openqabot.types.types import OBSBinary


@pytest.fixture
def mock_binary() -> OBSBinary:
    return OBSBinary("test_prj", "test_pkg", "test_repo", "x86_64")


@pytest.fixture
def sample_xml_content() -> bytes:
    return b"""
    <report>
        <binary name="bash" arch="x86_64" version="5.0" release="1.1" package="bash-main"/>
        <binary name="bash-doc" arch="noarch" version="5.0" release="1.1" package="bash-docs"/>
    </report>
    """


@pytest.mark.usefixtures("mock_binary")
def test_parse_source_report(mock_binary: OBSBinary, sample_xml_content: bytes, mocker: MockerFixture) -> None:
    mocker.patch("osc.core.get_binary_file")

    mock_tree = MagicMock()
    mock_tree.getroot.return_value = etree.fromstring(sample_xml_content)
    mocker.patch("lxml.etree.parse", return_value=mock_tree)

    packages = defaultdict(set)

    parse_source_report(mock_binary, "test.Source.report", packages)

    assert "x86_64" in packages
    assert "noarch" in packages

    x86_pkgs = list(packages["x86_64"])
    assert x86_pkgs[0].name == "bash"
    assert x86_pkgs[0].arch == "x86_64"

    assert len(packages["noarch"]) == 3


def test_find_source_reports(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.config.settings.obs_url", "http://obs.test")

    mock_repo = MagicMock()
    mock_repo.name = "standard"
    mock_repo.arch = "x86_64"

    mocker.patch("osc.core.get_repos_of_project", return_value=[mock_repo])
    mocker.patch("osc.core.get_binarylist", return_value=["pkg.rpm", "pkg.Source.report", "other.txt"])

    results = find_source_reports("test_prj", "test_pkg")

    assert len(results) == 1
    assert results[0] == "pkg.Source.report"


def test_load_packages_http_error(
    mock_binary: OBSBinary, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    mocker.patch(
        "openqabot.loader.sourcereport.find_source_reports",
        side_effect=HTTPError("http://obs.url", 404, "Not Found", Message(), None),
    )

    action = MagicMock()
    action.src_package = "test_pkg"
    packages: defaultdict[str, set] = defaultdict(set)

    load_packages_from_source_report(action, mock_binary, packages)

    assert "Failed to add packages from source report" in caplog.text
    assert "404" in caplog.text
