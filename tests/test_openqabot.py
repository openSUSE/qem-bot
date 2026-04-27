# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test OpenQABot."""

from __future__ import annotations

import logging
import os
from argparse import Namespace
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn
from urllib.parse import ParseResult, urlparse

import pytest
import responses
from typer.testing import CliRunner

from openqabot.args import app
from openqabot.args import main as args_main
from openqabot.config import QEM_DASHBOARD
from openqabot.errors import PostOpenQAError
from openqabot.main import main
from openqabot.openqa import OpenQAInterface
from openqabot.openqabot import OpenQABot

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

runner = CliRunner()


def test_no_args_prints_help() -> None:
    result = runner.invoke(app, [])
    # Typer/Click might exit with non-zero when showing help due to no args
    assert "Usage: " in result.stdout


def test_main_configs_not_dir_triggers_error_and_exit(tmp_path: Path, mocker: MockerFixture) -> None:
    non_existent = tmp_path / "does_not_exist"
    mock_log = mocker.patch("openqabot.args.log")

    result = runner.invoke(app, ["--token", "foo", "--configs", str(non_existent), "full-run"])

    assert result.exit_code == 1
    mock_log.error.assert_called()
    assert "Configuration error" in mock_log.error.call_args[0][0]


def test_main_debug_flag_sets_log_level(mocker: MockerFixture) -> None:
    mock_logger = mocker.Mock()
    mock_logger.setLevel = mocker.Mock()
    mocker.patch("openqabot.args.create_logger", return_value=mock_logger)
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("openqabot.args.OpenQABot").return_value.return_value = 0

    result = runner.invoke(app, ["--token", "foo", "--debug", "full-run"])
    assert result.exit_code == 0
    mock_logger.setLevel.assert_called_with(logging.DEBUG)


def test_main_keyboard_interrupt(mocker: MockerFixture) -> None:
    # We need to run main() and mock app() to raise KeyboardInterrupt
    mocker.patch("openqabot.main.app", side_effect=KeyboardInterrupt)
    mock_logger = mocker.Mock()
    mocker.patch("openqabot.main.create_logger", return_value=mock_logger)
    mock_exit = mocker.patch("sys.exit")

    main()

    mock_logger.info.assert_called_with("Interrupted by user")
    mock_exit.assert_called_with(1)


def test_main_missing_token_exits(mocker: MockerFixture) -> None:
    # Use CliRunner to test main app execution with missing token
    # We must NOT provide --token and not have it in env
    mocker.patch.dict(os.environ, {}, clear=True)
    mocker.patch("pathlib.Path.exists", return_value=True)

    result = runner.invoke(app, ["full-run"])
    assert result.exit_code == 1
    assert "Error: Missing option '--token' / '-t'." in result.output


def test_main_help_no_token(mocker: MockerFixture) -> None:
    # Test that --help works even without token
    mocker.patch.dict(os.environ, {}, clear=True)
    mocker.patch("sys.argv", ["qem-bot", "--help"])
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage: " in result.stdout


def test_main_help_subcommand_no_token(mocker: MockerFixture) -> None:
    # Test that full-run --help works even without token
    mocker.patch.dict(os.environ, {}, clear=True)
    mocker.patch("sys.argv", ["qem-bot", "full-run", "--help"])
    result = runner.invoke(app, ["full-run", "--help"])
    assert result.exit_code == 0
    assert "Usage: " in result.stdout


def test_main_missing_token_with_help_returns_early(mocker: MockerFixture) -> None:
    # Use mocker to capture sys.exit and print
    mock_exit = mocker.patch("sys.exit")
    mock_print = mocker.patch("builtins.print")
    # Ensure token is not in environment
    mocker.patch.dict(os.environ, {}, clear=True)
    # Mock sys.argv to simulate running with --help
    mocker.patch("sys.argv", ["qem-bot.py", "--help"])

    # We need to mock the context and its resilient_parsing attribute
    mock_ctx = mocker.Mock()
    mock_ctx.resilient_parsing = False
    mock_ctx.help_option_names = ["--help", "-h"]

    # Call the main callback directly
    # It should return early because --help is in sys.argv
    args_main(mock_ctx, configs=Path("/etc/openqabot"), token=None)

    # It should NOT exit and NOT print error
    assert not mock_exit.called
    assert not mock_print.called


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
