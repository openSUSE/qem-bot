# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import logging
import re
from argparse import Namespace
from typing import Any, cast
from unittest.mock import patch
from urllib.parse import urlparse

import pytest
import requests
from openqa_client.exceptions import RequestError

import responses
from openqabot.config import QEM_DASHBOARD
from openqabot.errors import PostOpenQAError
from openqabot.openqa import OpenQAInterface as oQAI
from responses import matchers


@pytest.fixture
def fake_osd_rsp() -> None:
    responses.add(
        responses.POST,
        re.compile(r"https://openqa.suse.de/"),
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


def test_bool() -> None:
    false_address = urlparse("http://fake.openqa.site")
    true_address = urlparse("https://openqa.suse.de")

    assert oQAI(Namespace(openqa_instance=true_address, token=""))
    assert not oQAI(Namespace(openqa_instance=false_address, token=""))


@responses.activate
def test_post_job_failed(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.openqa")
    client = oQAI(Namespace(openqa_instance=urlparse("https://openqa.suse.de"), token=""))
    client.retries = 0
    with pytest.raises(PostOpenQAError):
        client.post_job({"foo": "bar"})

    assert "openqa-cli api --host https://openqa.suse.de -X post isos foo=bar" in caplog.messages
    error = RequestError("POST", "no.where", 500, "no text")
    with patch("openqabot.openqa.OpenQA_Client.openqa_request", side_effect=error), pytest.raises(PostOpenQAError):
        client.post_job({"foo": "bar"})
    assert any("openQA API error" in m for m in caplog.messages)
    assert any("Job POST failed for settings" in m for m in caplog.messages)


@responses.activate
@pytest.mark.usefixtures("fake_osd_rsp")
def test_post_job_passed(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.openqa")
    client = oQAI(Namespace(openqa_instance=urlparse("https://openqa.suse.de"), token=""))
    client.post_job({"foo": "bar"})

    assert "openqa-cli api --host https://openqa.suse.de -X post isos foo=bar" in caplog.messages
    assert len(responses.calls) == 1
    assert responses.calls
    calls = cast("Any", responses.calls)
    assert calls[0].request.headers["User-Agent"] == "python-OpenQA_Client/qem-bot/1.0.0"
    assert calls[0].response.json() == {"bar": "foo"}


@responses.activate
@pytest.mark.usefixtures("fake_responses_failing_job_update")
def test_handle_job_not_found(caplog: pytest.LogCaptureFixture) -> None:
    client = oQAI(Namespace(openqa_instance=urlparse("https://openqa.suse.de"), token=""))
    client.handle_job_not_found(42)
    assert len(caplog.messages) == 2
    assert len(responses.calls) == 1
    assert "Job 42 not found on openQA, marking as obsolete on dashboard" in caplog.messages
    assert any("job not found" in m for m in caplog.messages)  # the 404 fixture is supposed to match


def test_get_methods_handle_errors_gracefully() -> None:
    client = oQAI(Namespace(openqa_instance=urlparse("https://openqa.suse.de"), token=""))
    error = RequestError("GET", "no.where", 500, "no text")
    with patch("openqabot.openqa.OpenQA_Client.openqa_request", side_effect=error):
        assert client.get_job_comments(42) == []
        assert not client.get_single_job(42)
        assert client.get_older_jobs(42, 0) == {"data": []}


def test_get_job_comments_request_exception(caplog: pytest.LogCaptureFixture) -> None:
    client = oQAI(Namespace(openqa_instance=urlparse("https://openqa.suse.de"), token=""))
    with patch(
        "openqabot.openqa.OpenQA_Client.openqa_request",
        side_effect=requests.exceptions.RequestException("Request failed"),
    ):
        assert client.get_job_comments(42) == []
    assert "openQA API error when fetching comments for job 42" in caplog.text
