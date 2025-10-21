from collections import namedtuple
import logging
from typing import Dict
from urllib.parse import urlparse, ParseResult

import pytest
import responses

from openqabot import QEM_DASHBOARD
from openqabot.openqabot import OpenQABot
import openqabot.openqabot
from openqabot.errors import PostOpenQAError

Namespace = namedtuple(
    "Namespace",
    [
        "dry",
        "ignore_onetime",
        "token",
        "singlearch",
        "openqa_instance",
        "configs",
        "disable_aggregates",
        "disable_incidents",
    ],
)


@pytest.fixture
def mock_openqa_passed(monkeypatch):
    class FakeClient:
        def __init__(self, args):
            self.url: ParseResult = args.openqa_instance
            self.qem_token: Dict[str, str] = {"Authorization": f"Token {args.token}"}

        def __bool__(self):
            return self.url.netloc == "openqa.suse.de"

        def post_job(self, *args, **kwargs):
            pass

    monkeypatch.setattr(openqabot.openqabot, "openQAInterface", FakeClient)


@pytest.fixture
def mock_openqa_exception(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def post_job(self, *args, **kwargs):
            raise PostOpenQAError

    monkeypatch.setattr(openqabot.openqabot, "openQAInterface", FakeClient)


@pytest.fixture
def mock_runtime(monkeypatch):
    class FakeWorker:
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, *args, **kwargs):
            return [{"qem": {"fake": "result"}, "openqa": {"fake", "result"}, "api": "bar"}]

    def f_load_metadata(*args, **kwds):
        return [FakeWorker()]

    monkeypatch.setattr(openqabot.openqabot, "load_metadata", f_load_metadata)

    def f_get_incidents(*args, **kwds):
        return [123]

    monkeypatch.setattr(openqabot.openqabot, "get_incidents", f_get_incidents)

    def f_get_onearch(*args, **kwds):
        return set()

    monkeypatch.setattr(openqabot.openqabot, "get_onearch", f_get_onearch)


@responses.activate
def test_passed(mock_runtime, mock_openqa_passed, caplog):
    caplog.set_level(logging.DEBUG)
    args = Namespace(
        False,
        False,
        "token",
        "single",
        urlparse("https://openqa.suse.de"),
        None,
        False,
        False,
    )
    bot = OpenQABot(args)

    responses.add(responses.PUT, f"{QEM_DASHBOARD}bar", json={"id": 234})
    bot()

    messages = [m[-1] for m in caplog.record_tuples]
    assert len(messages) == 7
    assert "1 incidents loaded from qem dashboard" in messages
    assert "Triggering 1 products in openQA" in messages


@responses.activate
def test_dry(mock_runtime, mock_openqa_passed, caplog):
    caplog.set_level(logging.DEBUG)
    args = Namespace(
        True,
        False,
        "token",
        "single",
        urlparse("https://openqa.suse.de"),
        None,
        False,
        False,
    )
    bot = OpenQABot(args)

    responses.add(responses.PUT, f"{QEM_DASHBOARD}bar")
    bot()

    messages = [m[-1] for m in caplog.record_tuples]
    assert len(messages) == 6
    assert "Would trigger 1 products in openQA"


@responses.activate
def test_passed_non_osd(mock_runtime, mock_openqa_passed, caplog):
    caplog.set_level(logging.DEBUG)
    args = Namespace(
        False,
        False,
        "token",
        "single",
        urlparse("https://openqa.opensuse.org"),
        None,
        False,
        False,
    )
    bot = OpenQABot(args)

    responses.add(responses.PUT, f"{QEM_DASHBOARD}bar")
    bot()

    messages = [m[-1] for m in caplog.record_tuples]
    assert len(messages) == 7
    assert "1 incidents loaded from qem dashboard" in messages
    assert "Triggering 1 products in openQA" in messages
    assert "No valid openQA configuration specified: '{'fake': 'result'}' not posted to dashboard" in messages


@responses.activate
def test_passed_post_osd_failed(mock_runtime, mock_openqa_exception, caplog):
    caplog.set_level(logging.DEBUG)
    args = Namespace(
        False,
        False,
        "token",
        "single",
        urlparse("https://openqa.suse.de"),
        None,
        False,
        False,
    )
    bot = OpenQABot(args)

    responses.add(responses.PUT, f"{QEM_DASHBOARD}bar")
    bot()

    messages = [m[-1] for m in caplog.record_tuples]
    assert len(messages) == 7
    assert "1 incidents loaded from qem dashboard" in messages
    assert "Triggering 1 products in openQA" in messages
    assert "POST failed, not updating dashboard" in messages
