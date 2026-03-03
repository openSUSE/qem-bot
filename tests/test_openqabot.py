# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test OpenQABot."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from openqabot.args import app
from openqabot.args import main as args_main
from openqabot.main import main

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
