# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test OpenQABot."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from openqabot.args import app
from openqabot.main import main

if TYPE_CHECKING:
    import pytest
    from pytest_mock import MockerFixture

runner = CliRunner()


def test_no_args_prints_help() -> None:
    result = runner.invoke(app, [])
    # Typer/Click might exit with non-zero when showing help due to no args
    assert "Usage: " in result.stdout


def test_main_configs_not_dir_triggers_error_and_exit(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch("openqabot.args.OpenQABot")
    mocker.patch("pathlib.Path.is_dir", return_value=False)

    # We need to capture logs
    with caplog.at_level(logging.ERROR):
        # running full-run which requires config
        result = runner.invoke(app, ["--token", "foo", "full-run"])

    assert result.exit_code == 1
    # Check caplog for the error message
    assert "Configuration error" in caplog.text


def test_main_debug_flag_sets_log_level(mocker: MockerFixture) -> None:
    mock_logger = mocker.Mock()
    mock_logger.setLevel = mocker.Mock()
    mocker.patch("openqabot.args.create_logger", return_value=mock_logger)
    mocker.patch("pathlib.Path.is_dir", return_value=True)
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


def test_main_exception(mocker: MockerFixture) -> None:
    # We need to run main() and mock app() to raise an Exception
    mocker.patch("openqabot.main.app", side_effect=Exception("something went wrong"))
    mock_logger = mocker.Mock()
    mocker.patch("openqabot.main.create_logger", return_value=mock_logger)
    mock_exit = mocker.patch("sys.exit")

    main()

    # The exception object itself is logged
    args, _ = mock_logger.error.call_args
    assert "something went wrong" in str(args[0])
    mock_exit.assert_called_with(1)


def test_main_missing_token_exits(mocker: MockerFixture) -> None:
    # Use CliRunner to test main app execution with missing token
    # We must NOT provide --token and not have it in env
    mocker.patch.dict(os.environ, {}, clear=True)
    # Mock configs dir to be True to avoid unrelated Configuration error if it fails later
    mocker.patch("pathlib.Path.is_dir", return_value=True)

    result = runner.invoke(app, ["full-run"])
    assert result.exit_code == 1
    assert (
        "Error: Missing option '--token' / '-t'." in result.stdout
        or "Error: Missing option '--token' / '-t'." in result.stderr
    )


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
