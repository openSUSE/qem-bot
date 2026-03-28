# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test OpenQA Client."""

import logging
import re
from typing import Any, cast
from unittest.mock import patch

import pytest
import requests
from openqa_client.exceptions import RequestError

import responses
from openqabot.config import QEM_DASHBOARD
from openqabot.errors import PostOpenQAError
from openqabot.openqa import OpenQAInterface as oQAI
from responses import matchers


@pytest.fixture
def fake_osd_rsp(fake_openqa_url: str) -> None:
    responses.add(
        responses.POST,
        re.compile(fake_openqa_url),
        json={"bar": "foo"},
        status=200,
    )


@pytest.fixture
def fake_responses_failing_job_update() -> None:
    responses.add(
        responses.PATCH,
        f"{QEM_DASHBOARD}api/jobs/42",
        body="updated job",
        status=200,
        match=[matchers.json_params_matcher({"obsolete": False})],  # should *not* match
    )
    responses.add(
        responses.PATCH,
        f"{QEM_DASHBOARD}api/jobs/42",
        body="job not found",  # we pretend the job update fails
        status=404,
        match=[matchers.json_params_matcher({"obsolete": True})],
    )


@responses.activate
def test_post_job_failed(caplog: pytest.LogCaptureFixture, fake_openqa_url: str) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.openqa")
    client = oQAI()
    client.retries = 0
    with pytest.raises(PostOpenQAError):
        client.post_job({"foo": "bar"})

    assert f"openqa-cli api --host {fake_openqa_url} -X post isos foo=bar" in caplog.messages
    error = RequestError("POST", "no.where", 500, "no text")
    with patch("openqabot.openqa.OpenQA_Client.openqa_request", side_effect=error), pytest.raises(PostOpenQAError):
        client.post_job({"foo": "bar"})
    assert any("openQA API error" in m for m in caplog.messages)
    assert any("Job POST failed for settings" in m for m in caplog.messages)


@responses.activate
@pytest.mark.usefixtures("fake_osd_rsp")
def test_post_job_passed(caplog: pytest.LogCaptureFixture, fake_openqa_url: str) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.openqa")
    client = oQAI()
    client.post_job({"foo": "bar"})

    assert f"openqa-cli api --host {fake_openqa_url} -X post isos foo=bar" in caplog.messages
    assert len(responses.calls) == 1
    assert responses.calls
    calls = cast("Any", responses.calls)
    assert calls[0].request.headers["User-Agent"] == "python-OpenQA_Client/qem-bot/1.0.0"
    assert calls[0].response.json() == {"bar": "foo"}


@responses.activate
@pytest.mark.usefixtures("fake_responses_failing_job_update")
def test_handle_job_not_found(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.openqa")
    client = oQAI()
    client.handle_job_not_found(42)
    assert len(caplog.messages) == 2
    assert len(responses.calls) == 1
    assert "Job 42 not found on openQA, marking as obsolete on dashboard" in caplog.messages
    assert any("job not found" in m for m in caplog.messages)  # the 404 fixture is supposed to match


def test_get_methods_handle_errors_gracefully() -> None:
    client = oQAI()
    error = RequestError("GET", "no.where", 500, "no text")
    with patch("openqabot.openqa.OpenQA_Client.openqa_request", side_effect=error):
        assert client.get_job_comments(42) == []
        assert not client.get_single_job(42)
        assert client.get_older_jobs(42, 0) == {"data": []}


def test_get_job_comments_request_exception(caplog: pytest.LogCaptureFixture) -> None:
    client = oQAI()
    with patch(
        "openqabot.openqa.OpenQA_Client.openqa_request",
        side_effect=requests.exceptions.RequestException("Request failed"),
    ):
        assert client.get_job_comments(42) == []
    assert "openQA API error when fetching comments for job 42" in caplog.text


def test_is_in_devel_group_allow_development_groups() -> None:
    """Test is_in_devel_group when allow_development_groups is True."""
    client = oQAI()
    # Settings expects a string or None
    with patch("openqabot.config.settings.allow_development_groups", "1"):
        # Should return False regardless of group name if allowed
        assert not client.is_in_devel_group({"group": "Devel Group"})
        assert not client.is_in_devel_group({"group": "Production"})


def test_is_in_devel_group_no_group_id() -> None:
    """Test is_in_devel_group when no group_id is present and not matching name."""
    client = oQAI()
    with patch("openqabot.config.settings.allow_development_groups", None):
        # No group_id and no "Devel"/"Test" in name -> should return False
        assert not client.is_in_devel_group({"group": "Production"})
        # No group_id but "Devel" in name -> should return True
        assert client.is_in_devel_group({"group": "Devel Group"})


@responses.activate
def test_get_job_group_info_success(fake_openqa_url: str) -> None:
    """Test get_job_group_info returns group data on success."""
    group_data = [{"id": 42, "name": "TestGroup", "description": "Test description"}]
    responses.add(
        responses.GET,
        f"{fake_openqa_url}/api/v1/job_groups/42",
        json=group_data,
        status=200,
    )
    client = oQAI()
    result = client.get_job_group_info(42)
    assert result == {"id": 42, "name": "TestGroup", "description": "Test description"}


@responses.activate
def test_get_job_group_info_empty_response(fake_openqa_url: str) -> None:
    """Test get_job_group_info returns None on empty response."""
    responses.add(responses.GET, f"{fake_openqa_url}/api/v1/job_groups/42", json=[], status=200)
    client = oQAI()
    result = client.get_job_group_info(42)
    assert result is None


@responses.activate
def test_get_job_group_info_error(fake_openqa_url: str, caplog: pytest.LogCaptureFixture) -> None:
    """Test get_job_group_info returns None on API error."""
    caplog.set_level(logging.ERROR, logger="bot.openqa")
    responses.add(
        responses.GET,
        f"{fake_openqa_url}/api/v1/job_groups/42",
        json={"error": "not found"},
        status=404,
    )
    client = oQAI()
    result = client.get_job_group_info(42)
    assert result is None
    assert "openQA API error when fetching job group 42" in caplog.text
