# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test OpenQABot simple."""

from __future__ import annotations

import logging
from argparse import Namespace
from typing import TYPE_CHECKING, Any, NoReturn
from urllib.parse import ParseResult, urlparse

import pytest
import responses

from openqabot.config import QEM_DASHBOARD
from openqabot.errors import PostOpenQAError
from openqabot.openqa import OpenQAInterface
from openqabot.openqabot import OpenQABot

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def mocked_openqa_bot() -> Namespace:
    return Namespace(
        dry=False,
        ignore_onetime=False,
        singlearch="single",
        configs=None,
        disable_aggregates=False,
        disable_submissions=False,
        submission=None,
    )


@pytest.fixture
def mock_openqa_passed(mocker: MockerFixture, fake_openqa_url: str) -> Any:
    class FakeClient:
        def __init__(self) -> None:
            self.url: ParseResult = urlparse(fake_openqa_url)

        def __bool__(self) -> bool:
            return self.url.netloc == "openqa.suse.de"

        def post_job(self, *args: Any, **kwargs: Any) -> None:
            pass

    return mocker.patch("openqabot.openqabot.OpenQAInterface", FakeClient)


@pytest.fixture
def mock_openqa_exception(mocker: MockerFixture) -> Any:
    class FakeClient:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def post_job(self, *_args: Any, **_kwargs: Any) -> NoReturn:  # noqa: PLR6301
            raise PostOpenQAError

    return mocker.patch("openqabot.openqabot.OpenQAInterface", FakeClient)


@pytest.fixture
def mock_runtime(mocker: MockerFixture) -> None:
    class FakeWorker:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        def __call__(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            return [{"qem": {"fake": "result"}, "openqa": {"fake", "result"}, "api": "bar"}]

    def f_load_metadata(*_args: Any, **_kwds: Any) -> list[FakeWorker]:
        return [FakeWorker()]

    def f_get_submissions(*_args: Any, **_kwds: Any) -> list[Any]:
        sub = mocker.MagicMock()
        sub.log_skipped = mocker.Mock()
        return [sub]

    def f_get_onearch(*_args: Any, **_kwds: Any) -> set[Any]:
        return set()

    mocker.patch("openqabot.openqabot.load_metadata", side_effect=f_load_metadata)
    mocker.patch("openqabot.openqabot.get_submissions", side_effect=f_get_submissions)
    mocker.patch("openqabot.openqabot.get_onearch", side_effect=f_get_onearch)


@responses.activate
@pytest.mark.usefixtures("mock_runtime", "mock_openqa_passed")
def test_passed(mocked_openqa_bot: Namespace, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    bot = OpenQABot(mocked_openqa_bot)
    responses.add(responses.PUT, f"{QEM_DASHBOARD}bar", json={"id": 234})
    bot()

    assert len(caplog.messages) == 7
    assert "Loaded 1 submissions from QEM Dashboard" in caplog.messages
    assert "Triggering 1 products in openQA" in caplog.messages


@responses.activate
@pytest.mark.usefixtures("mock_runtime", "mock_openqa_passed")
def test_passed_non_osd(mocked_openqa_bot: Namespace, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    bot = OpenQABot(mocked_openqa_bot)
    responses.add(responses.PUT, f"{QEM_DASHBOARD}bar")
    bot()

    assert len(caplog.messages) == 7
    assert "Loaded 1 submissions from QEM Dashboard" in caplog.messages
    assert "Triggering 1 products in openQA" in caplog.messages
    assert "Skipping dashboard update: No valid openQA configuration found for data" in caplog.text


@responses.activate
@pytest.mark.usefixtures("mock_runtime", "mock_openqa_exception")
def test_passed_post_osd_failed(mocked_openqa_bot: Namespace, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    bot = OpenQABot(mocked_openqa_bot)
    responses.add(responses.PUT, f"{QEM_DASHBOARD}bar")
    bot()

    assert len(caplog.messages) == 7
    assert "Loaded 1 submissions from QEM Dashboard" in caplog.messages
    assert "Triggering 1 products in openQA" in caplog.messages
    assert "Skipping dashboard update: Job post failed" in caplog.messages


@responses.activate
@pytest.mark.usefixtures("mock_runtime", "mock_openqa_passed")
def test_post_qem_success(mocked_openqa_bot: Namespace, mocker: MockerFixture) -> None:

    bot = OpenQABot(mocked_openqa_bot)
    bot.openqa = mocker.Mock(spec=OpenQAInterface)
    test_api = "api/jobs/incident/1"
    test_data = {"status": "passed", "job_id": 999}
    responses.add(
        responses.PUT,
        f"{QEM_DASHBOARD}{test_api}",
        json={"id": 12345},
        status=200,
    )

    bot.post_qem(test_data, test_api)

    assert len(responses.calls) == 1
    assert responses.calls[0].request.url == f"{QEM_DASHBOARD}{test_api}"
