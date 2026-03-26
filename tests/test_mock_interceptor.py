# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Tests for mock interceptor."""

from io import BytesIO
from typing import Any
from unittest.mock import patch

import pytest
import requests
import responses

from openqabot.mock_interceptor import (
    MockInterceptorState,
    gitea_pr_details_callback,
    gitea_pulls_callback,
    mock_http_get,
    openqa_jobs_callback,
    patchinfo_callback,
    read_fixture,
    setup_mock_responses,
    smelt_graphql_callback,
)


class MockRequest(requests.PreparedRequest):
    """Mock request class for testing callbacks."""

    def __init__(self, url: str) -> None:
        """Initialize mock request."""
        super().__init__()
        self.url = url


@pytest.fixture(autouse=True)
def reset_mock_state() -> Any:
    """Reset mock state before each test.

    Yields:
        None

    """
    MockInterceptorState.started = False
    MockInterceptorState.osc_patcher = None
    MockInterceptorState.osc_conf_patcher = None
    yield
    responses.stop()
    MockInterceptorState.started = False
    MockInterceptorState.osc_patcher = None
    MockInterceptorState.osc_conf_patcher = None


def test_setup_mock_responses() -> None:
    """Test setup of mock responses."""
    with patch("responses.start") as mock_start:
        setup_mock_responses()
        mock_start.assert_called_once()
        assert MockInterceptorState.started is True

        # Call again to test early return
        setup_mock_responses()
        mock_start.assert_called_once()


def test_setup_mock_responses_no_osc(mocker: Any) -> None:
    """Test setup when osc is not available."""
    mocker.patch("openqabot.mock_interceptor.HAS_OSC", new=False)
    with patch("responses.start"):
        setup_mock_responses()
        assert MockInterceptorState.osc_patcher is None
        assert MockInterceptorState.osc_conf_patcher is None


def test_setup_mock_responses_no_start(mocker: Any) -> None:
    """Test setup when patcher has no start method."""
    mocker.patch("openqabot.mock_interceptor.patch", return_value=object())
    with patch("responses.start"):
        setup_mock_responses()
        assert MockInterceptorState.osc_patcher is not None
        assert not hasattr(MockInterceptorState.osc_patcher, "start")
        assert MockInterceptorState.osc_conf_patcher is not None
        assert not hasattr(MockInterceptorState.osc_conf_patcher, "start")
        assert MockInterceptorState.started is True


def test_read_fixture() -> None:
    """Test fixture reading helper."""
    with patch("openqabot.mock_interceptor.Path") as mock_path:
        mock_path.return_value.exists.return_value = True
        mock_path.return_value.read_text.return_value = "content"
        assert read_fixture("test") == "content"

        mock_path.return_value.exists.return_value = False
        assert not read_fixture("test")


def test_gitea_pulls_callback() -> None:
    """Test Gitea pull requests list mock callback."""
    with patch("openqabot.mock_interceptor.read_fixture") as mock_read:
        mock_read.return_value = "fixture_data"
        assert gitea_pulls_callback(MockRequest("http://test/page=1")) == (200, {}, "fixture_data")
        assert gitea_pulls_callback(MockRequest("http://test/no_page")) == (200, {}, "fixture_data")
        assert gitea_pulls_callback(MockRequest("http://test/page=2")) == (200, {}, "[]")


def test_gitea_pr_details_callback() -> None:
    """Test Gitea PR details mock callbacks."""
    with patch("openqabot.mock_interceptor.read_fixture") as mock_read:
        mock_read.return_value = "details_data"
        assert gitea_pr_details_callback(MockRequest("http://test/reviews")) == (200, {}, "details_data")
        assert gitea_pr_details_callback(MockRequest("http://test/comments")) == (200, {}, "details_data")
        assert gitea_pr_details_callback(MockRequest("http://test/files")) == (200, {}, "details_data")
        assert gitea_pr_details_callback(MockRequest("http://test/unknown")) == (404, {}, "{}")


def test_smelt_graphql_callback() -> None:
    """Test SMELT GraphQL mock callback."""
    status, _, data = smelt_graphql_callback(MockRequest("http://test"))
    assert status == 200
    assert "incidents" in data
    assert "SUSE:Maintenance:100" in data


def test_openqa_jobs_callback() -> None:
    """Test openQA jobs mock callback."""
    status, _, data = openqa_jobs_callback(MockRequest("http://test"))
    assert status == 200
    assert "jobs" in data
    assert "mock_job_git" in data


def test_patchinfo_callback() -> None:
    """Test patchinfo mock callback."""
    with patch("openqabot.mock_interceptor.read_fixture") as mock_read:
        mock_read.return_value = "patchinfo_data"
        assert patchinfo_callback(MockRequest("http://test")) == (200, {}, "patchinfo_data")


def test_mock_http_get() -> None:
    """Test OBS HTTP GET mock function."""
    with patch("openqabot.mock_interceptor.read_fixture") as mock_read:
        mock_read.return_value = "xml_content"
        result = mock_http_get("http://obs/build/SUSE:SLFO:test/_result")
        assert isinstance(result, BytesIO)
        assert result.read() == b"xml_content"
        mock_read.assert_called_with("build-results-124-SUSE:SLFO:test.xml")

        mock_read.return_value = ""
        mock_read.side_effect = ["", "empty_xml"]
        result = mock_http_get("http://obs/build/SUSE:SLFO:test/_result")
        assert result.read() == b"empty_xml"

        result = mock_http_get("http://obs/other/path")
        assert result.read() == b""
