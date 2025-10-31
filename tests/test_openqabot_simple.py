# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# ruff: noqa: S106 "Possible hardcoded password assigned to argument"

import logging
from collections import namedtuple
from typing import Any, Dict, List, NoReturn, Set
from urllib.parse import ParseResult, urlparse

import pytest
from _pytest.logging import LogCaptureFixture
from pytest import MonkeyPatch

import openqabot.openqabot
import responses
from openqabot import QEM_DASHBOARD
from openqabot.errors import PostOpenQAError
from openqabot.openqabot import OpenQABot

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
def mock_openqa_passed(monkeypatch: MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, args: Any) -> None:
            self.url: ParseResult = args.openqa_instance
            self.qem_token: Dict[str, str] = {"Authorization": f"Token {args.token}"}

        def __bool__(self) -> bool:
            return self.url.netloc == "openqa.suse.de"

        def post_job(self, *args: Any, **kwargs: Any) -> None:
            pass

    monkeypatch.setattr(openqabot.openqabot, "openQAInterface", FakeClient)


@pytest.fixture
def mock_openqa_exception(monkeypatch: MonkeyPatch) -> None:
    class FakeClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def post_job(self, *_args: Any, **_kwargs: Any) -> NoReturn:
            raise PostOpenQAError

    monkeypatch.setattr(openqabot.openqabot, "openQAInterface", FakeClient)


@pytest.fixture
def mock_runtime(monkeypatch: MonkeyPatch) -> None:
    class FakeWorker:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def __call__(self, *_args: Any, **_kwargs: Any) -> List[Dict[str, Any]]:
            return [{"qem": {"fake": "result"}, "openqa": {"fake", "result"}, "api": "bar"}]

    def f_load_metadata(*_args: Any, **_kwds: Any) -> List[FakeWorker]:
        return [FakeWorker()]

    monkeypatch.setattr(openqabot.openqabot, "load_metadata", f_load_metadata)

    def f_get_incidents(*_args: Any, **_kwds: Any) -> List[int]:
        return [123]

    monkeypatch.setattr(openqabot.openqabot, "get_incidents", f_get_incidents)

    def f_get_onearch(*_args: Any, **_kwds: Any) -> Set[Any]:
        return set()

    monkeypatch.setattr(openqabot.openqabot, "get_onearch", f_get_onearch)


@responses.activate
@pytest.mark.usefixtures("mock_runtime", "mock_openqa_passed")
def test_passed(caplog: LogCaptureFixture) -> None:
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
@pytest.mark.usefixtures("mock_runtime", "mock_openqa_passed")
def test_dry(caplog: LogCaptureFixture) -> None:
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
@pytest.mark.usefixtures("mock_runtime", "mock_openqa_passed")
def test_passed_non_osd(caplog: LogCaptureFixture) -> None:
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
@pytest.mark.usefixtures("mock_runtime", "mock_openqa_exception")
def test_passed_post_osd_failed(caplog: LogCaptureFixture) -> None:
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
