# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test repository URL computation."""

from __future__ import annotations

import json
import logging
from http import HTTPStatus
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import requests

from openqabot.loader import repourl
from openqabot.types.types import Repos

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.mark.parametrize(
    ("repo", "product_repo", "published", "expected", "expected_log"),
    [
        (Repos("SUSE:SLFO", "1.3:PullRequest:10936:SLES", "aarch64"), None, set(), ["SLES"], ""),
        (Repos("SUSE:SLFO", "1.3:PullRequest:10936:SLES", "aarch64"), "SLES", set(), ["SLES"], ""),
        (
            Repos("SUSE:SLFO", "1.3:PullRequest:10936:SLES", "aarch64"),
            ["SLES-HA", "SLES"],
            set(),
            ["SLES-HA", "SLES"],
            "",
        ),
        (
            Repos("SUSE:SLFO", "1.3:PullRequest:10936:SLES", "aarch64"),
            ["SLES-SAP"],
            {"SLE-BCI", "SLES", "SLES-SAP"},
            ["SLES-SAP"],
            "",
        ),
        (
            Repos("SUSE:SLFO", "1.3:PullRequest:10936:SLES-NVIDIA", "aarch64"),
            ["SLES"],
            {"SLES-NVIDIA"},
            ["SLES-NVIDIA"],
            "",
        ),
        (Repos("SUSE:SLFO", "1.3:PullRequest:10936:SLES-NVIDIA", "aarch64"), ["SLES"], set(), ["SLES"], ""),
        (
            Repos("SUSE:SLFO", "1.3:PullRequest:10936:SLES-NVIDIA", "aarch64"),
            None,
            {"SLES-NVIDIA"},
            ["SLES-NVIDIA"],
            "",
        ),
        (
            Repos("SUSE:SLFO", "Kernel:1.0:PullRequest:385:SL-Micro-6.1", "ppc64le"),
            None,
            {"SL-Micro", "SL-Micro-Extras"},
            ["SL-Micro"],
            "publishes product SL-Micro, not SL-Micro-6.1",
        ),
        (
            Repos("SUSE:SLFO", "Kernel:1.0:PullRequest:385:SL-Micro-6.1", "ppc64le"),
            None,
            {"SLES", "SL-Micro-Extras"},
            ["SL-Micro-6.1"],
            "publishes ['SL-Micro-Extras', 'SLES'] instead of the configured []",
        ),
        (
            Repos("SUSE:SLFO", "1.3:PullRequest:10936:SLES-NVIDIA", "aarch64"),
            ["SLES"],
            {"SLES-HA"},
            ["SLES-NVIDIA"],
            "publishes ['SLES-HA'] instead of the configured ['SLES']",
        ),
        (Repos("SUSE:SLFO", "1.2", "aarch64"), ["SLES"], {"SLES-NVIDIA"}, ["SLES"], ""),
        (Repos("SLE-Module-Basesystem", "15-SP7", "x86_64"), ["SLES"], {"SLES"}, ["SLES"], ""),
        (Repos("SLE-Module-Basesystem", "15-SP7", "x86_64"), None, set(), [""], ""),
    ],
)
def test_product_names_for_channel(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    repo: Repos,
    product_repo: list[str] | str | None,
    published: set[str],
    expected: list[str],
    expected_log: str,
) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.repourl")
    mocker.patch.object(repourl, "published_products", return_value=frozenset(published))

    assert repourl.product_names_for_channel(repo, product_repo) == expected
    assert (expected_log in caplog.text) if expected_log else not caplog.records


def test_published_products_of_a_project(mocker: MockerFixture) -> None:
    repourl.repo_listing.cache_clear()
    mocked_response = mocker.Mock()
    mocked_response.json.return_value = {
        "data": [
            {"name": "SLES-SAP-16.1-ppc64le"},
            {"name": "SLES-SAP-16.1-ppc64le-Debug"},
            {"name": "SLES-16.1-x86_64"},
            {"name": "SLES-NVIDIA-16.1-aarch64"},
            {"name": "repodata"},
        ]
    }
    mocker.patch("openqabot.loader.repourl.retried_requests.get", return_value=mocked_response)

    assert repourl.published_products("SUSE:SLFO:1.3:PullRequest:10936:SLES", "ppc64le") == frozenset({"SLES-SAP"})


def test_published_products_of_unreadable_project(mocker: MockerFixture) -> None:
    repourl.repo_listing.cache_clear()
    mocked_response = mocker.Mock()
    mocked_response.raise_for_status.side_effect = requests.exceptions.HTTPError
    mocker.patch("openqabot.loader.repourl.retried_requests.get", return_value=mocked_response)

    assert repourl.published_products("SUSE:SLFO:1.3:PullRequest:10936:SLES", "ppc64le") == frozenset()


def test_repo_listing_of_invalid_json(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.repourl")
    mocked_response = MagicMock()
    mocked_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
    mocker.patch.object(repourl.retried_requests, "get", return_value=mocked_response)

    assert repourl.repo_listing("project", "repo") is None
    assert "Invalid JSON document" in caplog.text


def test_repo_listing_of_requests_json_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.repourl")
    mocked_response = MagicMock()
    mocked_response.json.side_effect = requests.exceptions.JSONDecodeError("msg", "doc", 0)
    mocker.patch.object(repourl.retried_requests, "get", return_value=mocked_response)

    assert repourl.repo_listing("project", "repo") is None
    assert "Invalid JSON document" in caplog.text


@pytest.mark.parametrize(
    ("response", "expected_log_level"),
    [
        pytest.param(None, "warning"),
        pytest.param(MagicMock(status_code=HTTPStatus.NOT_FOUND), "info"),
        pytest.param(MagicMock(status_code=HTTPStatus.INTERNAL_SERVER_ERROR), "warning"),
    ],
)
def test_repo_listing_of_an_unreadable_repository(
    mocker: MockerFixture, response: MagicMock | None, *, expected_log_level: str
) -> None:
    mock_log = mocker.patch("openqabot.loader.repourl.log")
    mocked_response = MagicMock()
    mocked_response.raise_for_status.side_effect = requests.exceptions.HTTPError("error", response=response)
    mocker.patch.object(repourl.retried_requests, "get", return_value=mocked_response)

    assert repourl.repo_listing("project", "repo") is None
    assert mock_log.info.called is (expected_log_level == "info")
    assert mock_log.warning.called is (expected_log_level == "warning")


def test_repo_listing_on_request_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="bot.loader.repourl")
    mocker.patch("openqabot.loader.repourl.retried_requests.get", side_effect=requests.RequestException("error"))

    assert repourl.repo_listing("project", "repo") is None
    assert "Product version unresolved" in caplog.text


def test_repo_listing_without_a_data_field(mocker: MockerFixture) -> None:
    mocked_response = MagicMock()
    mocked_response.json.return_value = {"rows": []}
    mocker.patch.object(repourl.retried_requests, "get", return_value=mocked_response)

    assert repourl.repo_listing("project", "repo") is None
