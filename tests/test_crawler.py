# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test Crawler class."""

from unittest.mock import MagicMock

import pytest
import requests
from requests.exceptions import RequestException

from openqabot.loader.crawler import Crawler


@pytest.fixture
def crawler() -> Crawler:
    return Crawler(verify=True)


def test_get_regex_match_success(crawler: Crawler, mocker: MagicMock) -> None:
    """Cover successful match return."""
    mocker.patch.object(crawler, "crawl", return_value=["SLES-15.5.iso", "other.txt"])
    regex = r"SLES-(?P<version>\d+\.\d+)\.iso"

    match = crawler.get_regex_match_from_url("http://url", regex)
    assert match is not None
    assert match.group("version") == "15.5"


def test_get_regex_match_empty_packages(crawler: Crawler, mocker: MagicMock) -> None:
    """Cover branch where crawl returns nothing."""
    mocker.patch.object(crawler, "crawl", return_value=[])
    assert crawler.get_regex_match_from_url("http://url", "regex") is None


def test_get_regex_match_multiple_matches(
    crawler: Crawler, mocker: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Cover warning when multiple items match regex."""
    mocker.patch.object(crawler, "crawl", return_value=["match1.iso", "match2.iso"])

    result = crawler.get_regex_match_from_url("http://url", r".*\.iso")
    assert "found more than one match" in caplog.text
    assert result is not None
    assert result.group(0) == "match1.iso"


def test_get_regex_match_no_filtered_results(
    crawler: Crawler, mocker: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Cover branch where items exist but none match regex."""
    mocker.patch.object(crawler, "crawl", return_value=["wrong.txt"])

    assert crawler.get_regex_match_from_url("http://url", r".*\.iso") is None
    assert "Nothing match" in caplog.text


def test_crawl_success(crawler: Crawler, mocker: MagicMock) -> None:
    """Cover standard successful JSON parsing."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "data": [
            {"name": "file1.iso"},
            {"name": "subdir/"},
            {"name": "file2.rpm"},
        ]
    }
    mocker.patch.object(crawler.retry_session, "get", return_value=mock_resp)

    result = crawler.crawl("http://url")
    assert result == ["file1.iso", "file2.rpm"]


def test_crawl_request_exception(crawler: Crawler, mocker: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    """Cover connection/request errors."""
    mocker.patch.object(crawler.retry_session, "get", side_effect=RequestException("Failed"))

    result = crawler.crawl("http://url")
    assert result == []
    assert "Failed" in caplog.text


def test_crawl_json_decode_error(crawler: Crawler, mocker: MagicMock, caplog: pytest.LogCaptureFixture) -> None:
    """Cover invalid JSON response."""
    mock_resp = MagicMock()
    # Trigger the requests-specific JSONDecodeError
    mock_resp.json.side_effect = requests.exceptions.JSONDecodeError("Bad JSON", "", 0)
    mocker.patch.object(crawler.retry_session, "get", return_value=mock_resp)

    result = crawler.crawl("http://url")
    assert result == []
    assert "exception occured" in caplog.text


def test_crawler_init_settings(crawler: Crawler) -> None:
    """Cover __init__ and retry adapter mounting."""
    assert crawler.verify is True
    assert "https://" in crawler.retry_session.adapters
    assert "http://" in crawler.retry_session.adapters
