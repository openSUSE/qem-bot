import logging
import re
from collections import namedtuple
from urllib.parse import urlparse

import pytest
import responses
from responses import matchers

from openqabot.errors import PostOpenQAError
from openqabot.openqa import openQAInterface as oQAI
from openqabot import QEM_DASHBOARD

_args = namedtuple("Args", ("openqa_instance", "token"))


@pytest.fixture(scope="function")
def fake_osd_rsp(request):
    def reply_callback(request):
        return (200, request.headers, b'{"bar":"foo"}')

    responses.add_callback(
        responses.POST,
        re.compile(r"https://openqa.suse.de/"),
        callback=reply_callback,
    )


@pytest.fixture(scope="function")
def fake_responses_failing_job_update():
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


def test_bool():
    false_address = urlparse("http://fake.openqa.site")
    true_address = urlparse("https://openqa.suse.de")

    assert oQAI(_args(true_address, ""))
    assert not oQAI(_args(false_address, ""))


@responses.activate
def test_post_job_failed(caplog):
    caplog.set_level(logging.DEBUG, logger="bot.openqa")
    client = oQAI(_args(urlparse("https://openqa.suse.de"), ""))
    client.retries = 0
    with pytest.raises(PostOpenQAError):
        client.post_job({"foo": "bar"})

    messages = [x[-1] for x in caplog.record_tuples]
    assert "openqa-cli api --host https://openqa.suse.de -X post isos foo=bar" in messages


@responses.activate
def test_post_job_passed(caplog, fake_osd_rsp):
    caplog.set_level(logging.DEBUG, logger="bot.openqa")
    client = oQAI(_args(urlparse("https://openqa.suse.de"), ""))
    client.post_job({"foo": "bar"})

    messages = [x[-1] for x in caplog.record_tuples]
    assert "openqa-cli api --host https://openqa.suse.de -X post isos foo=bar" in messages
    assert len(responses.calls) == 1
    assert responses.calls[0].response.headers["User-Agent"] == "python-OpenQA_Client/qem-bot/1.0.0"
    assert responses.calls[0].response.json() == {"bar": "foo"}


@responses.activate
def test_handle_job_not_found(caplog, fake_responses_failing_job_update):
    client = oQAI(_args(urlparse("https://openqa.suse.de"), ""))
    client.handle_job_not_found(42)
    messages = [x[-1] for x in caplog.record_tuples]
    assert len(messages) == 2
    assert len(responses.calls) == 1
    assert "Job 42 not found in openQA, marking as obsolete on dashboard" in messages
    assert "job not found" in messages  # the 404 fixture is supposed to match
