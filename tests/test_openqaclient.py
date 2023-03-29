import logging
import re
from urllib.parse import urlparse

import pytest
import responses

from openqabot.errors import PostOpenQAError
from openqabot.openqa import openQAInterface as oQAI


@pytest.fixture(scope="function")
def fake_osd_rsp(request):
    def reply_callback(request):
        return (200, request.headers, b'{"bar":"foo"}')

    responses.add_callback(
        responses.POST,
        re.compile(r"https://openqa.suse.de/"),
        callback=reply_callback,
    )


def test_bool():
    false_address = urlparse("http://fake.openqa.site")
    true_address = urlparse("https://openqa.suse.de")

    assert oQAI(true_address)
    assert not oQAI(false_address)


@responses.activate
def test_post_job_failed(caplog):
    caplog.set_level(logging.DEBUG, logger="bot.openqa")
    client = oQAI(urlparse("https://openqa.suse.de"))
    client.retries = 0
    with pytest.raises(PostOpenQAError):
        client.post_job({"foo": "bar"})

    messages = [x[-1] for x in caplog.record_tuples]
    assert (
        "openqa-cli api --host https://openqa.suse.de -X post isos foo=bar" in messages
    )


@responses.activate
def test_post_job_passed(caplog, fake_osd_rsp):
    caplog.set_level(logging.DEBUG, logger="bot.openqa")
    client = oQAI(urlparse("https://openqa.suse.de"))
    client.post_job({"foo": "bar"})

    messages = [x[-1] for x in caplog.record_tuples]
    assert (
        "openqa-cli api --host https://openqa.suse.de -X post isos foo=bar" in messages
    )
    assert len(responses.calls) == 1
    assert (
        responses.calls[0].response.headers["User-Agent"]
        == "python-OpenQA_Client/qem-bot/1.0.0"
    )
    assert responses.calls[0].response.json() == {"bar": "foo"}
