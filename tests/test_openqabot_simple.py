# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# ruff: noqa: S106 "Possible hardcoded password assigned to argument"

import logging
from collections.abc import Generator
from typing import Any, NamedTuple, NoReturn
from unittest.mock import patch
from urllib.parse import ParseResult, urlparse

import pytest

import openqabot.openqabot
import responses
from openqabot.config import QEM_DASHBOARD
from openqabot.errors import PostOpenQAError


class Namespace(NamedTuple):
    dry: bool
    ignore_onetime: bool
    token: str
    singlearch: str
    openqa_instance: str
    configs: str
    disable_aggregates: bool
    disable_incidents: bool


@pytest.fixture
def mock_openqa_passed() -> Generator[None, None, None]:
    class FakeClient:
        def __init__(self, args: Namespace) -> None:
            self.url: ParseResult = args.openqa_instance
            self.qem_token: dict[str, str] = {"Authorization": f"Token {args.token}"}

        def __bool__(self) -> bool:
            return self.url.netloc == "openqa.suse.de"

        def post_job(self, *args: Any, **kwargs: Any) -> None:
            pass

    with patch("openqabot.openqabot.openQAInterface", FakeClient):
        yield


@pytest.fixture
def mock_openqa_exception() -> Generator[None, None, None]:
    class FakeClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def post_job(self, *_args: Any, **_kwargs: Any) -> NoReturn:
            raise PostOpenQAError

    with patch("openqabot.openqabot.openQAInterface", FakeClient):
        yield


@pytest.fixture
def mock_runtime() -> Generator[None, None, None]:
    class FakeWorker:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def __call__(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            return [{"qem": {"fake": "result"}, "openqa": {"fake", "result"}, "api": "bar"}]

    def f_load_metadata(*_args: Any, **_kwds: Any) -> list[FakeWorker]:
        return [FakeWorker()]

    def f_get_incidents(*_args: Any, **_kwds: Any) -> list[int]:
        return [123]

    def f_get_onearch(*_args: Any, **_kwds: Any) -> set[Any]:
        return set()

    with (
        patch("openqabot.openqabot.load_metadata", side_effect=f_load_metadata),
        patch("openqabot.openqabot.get_incidents", side_effect=f_get_incidents),
        patch("openqabot.openqabot.get_onearch", side_effect=f_get_onearch),
    ):
        yield


@responses.activate
@pytest.mark.usefixtures("mock_runtime", "mock_openqa_passed")
def test_passed(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    args = Namespace(
        dry=False,
        ignore_onetime=False,
        token="token",
        singlearch="single",
        openqa_instance=urlparse("https://openqa.suse.de"),
        configs=None,
        disable_aggregates=False,
        disable_incidents=False,
    )
    bot = openqabot.openqabot.OpenQABot(args)

    responses.add(responses.PUT, f"{QEM_DASHBOARD}bar", json={"id": 234})
    bot()

    messages = [m[-1] for m in caplog.record_tuples]
    assert len(messages) == 7
    assert "1 incidents loaded from qem dashboard" in messages
    assert "Triggering 1 products in openQA" in messages


@responses.activate
@pytest.mark.usefixtures("mock_runtime", "mock_openqa_passed")
def test_dry(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    args = Namespace(
        dry=True,
        ignore_onetime=False,
        token="token",
        singlearch="single",
        openqa_instance=urlparse("https://openqa.suse.de"),
        configs=None,
        disable_aggregates=False,
        disable_incidents=False,
    )
    bot = openqabot.openqabot.OpenQABot(args)

    responses.add(responses.PUT, f"{QEM_DASHBOARD}bar")
    bot()

    messages = [m[-1] for m in caplog.record_tuples]
    assert len(messages) == 6
    assert "Would trigger 1 products in openQA"


@responses.activate
@pytest.mark.usefixtures("mock_runtime", "mock_openqa_passed")
def test_passed_non_osd(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    args = Namespace(
        dry=False,
        ignore_onetime=False,
        token="token",
        singlearch="single",
        openqa_instance=urlparse("https://openqa.opensuse.org"),
        configs=None,
        disable_aggregates=False,
        disable_incidents=False,
    )
    bot = openqabot.openqabot.OpenQABot(args)

    responses.add(responses.PUT, f"{QEM_DASHBOARD}bar")
    bot()

    messages = [m[-1] for m in caplog.record_tuples]
    assert len(messages) == 7
    assert "1 incidents loaded from qem dashboard" in messages
    assert "Triggering 1 products in openQA" in messages
    assert "No valid openQA configuration specified: '{'fake': 'result'}' not posted to dashboard" in messages


@responses.activate
@pytest.mark.usefixtures("mock_runtime", "mock_openqa_exception")
def test_passed_post_osd_failed(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    args = Namespace(
        dry=False,
        ignore_onetime=False,
        token="token",
        singlearch="single",
        openqa_instance=urlparse("https://openqa.suse.de"),
        configs=None,
        disable_aggregates=False,
        disable_incidents=False,
    )
    bot = openqabot.openqabot.OpenQABot(args)

    responses.add(responses.PUT, f"{QEM_DASHBOARD}bar")
    bot()

    messages = [m[-1] for m in caplog.record_tuples]
    assert len(messages) == 7
    assert "1 incidents loaded from qem dashboard" in messages
    assert "Triggering 1 products in openQA" in messages
    assert "POST failed, not updating dashboard" in messages
