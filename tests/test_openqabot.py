# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

import contextlib
import logging
import sys
from unittest.mock import MagicMock, patch

import pytest
from pytest_mock import MockerFixture

from openqabot.main import main  # SUT


def test_help() -> None:
    with patch.object(sys, "argv", ["--help"]), pytest.raises(SystemExit):
        main()


def test_no_args_prints_help() -> None:
    with (
        patch.object(sys, "argv", []),
        patch("openqabot.args.ArgumentParser.print_help"),
        pytest.raises(SystemExit),
    ):
        main()


def test_main_configs_not_dir_triggers_error_and_exit(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mock_configs_path = MagicMock()
    mock_configs_path.is_dir.return_value = False

    mock_args = MagicMock()
    mock_args.configs = mock_configs_path
    mock_args.token = "dummy_token"  # noqa: S105
    del mock_args.no_config
    mocker.patch("openqabot.args.ArgumentParser.parse_args", return_value=mock_args)

    mock_sys_exit = MagicMock(side_effect=SystemExit(1))
    caplog.set_level(logging.ERROR)

    with patch("sys.exit", side_effect=mock_sys_exit), pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    mock_sys_exit.assert_called_once_with(1)
    assert "not a valid directory with config files" in caplog.text


def test_main_empty_argv_prints_help_and_exits() -> None:
    mock_print_help = MagicMock()
    mock_sys_exit = MagicMock(side_effect=SystemExit(0))

    with (
        patch.object(sys, "argv", []),
        patch("openqabot.args.ArgumentParser.print_help", mock_print_help),
        patch("sys.exit", mock_sys_exit),
        pytest.raises(SystemExit) as excinfo,
    ):
        main()

    mock_print_help.assert_called_once()
    mock_sys_exit.assert_called_once_with(0)
    assert excinfo.value.code == 0


def test_main_debug_flag_sets_log_level() -> None:
    mock_configs_path = MagicMock()
    mock_configs_path.is_dir.return_value = True

    mock_args_debug_true = MagicMock()
    mock_args_debug_true.configs = mock_configs_path
    mock_args_debug_true.debug = True
    mock_args_debug_true.token = "dummy_token"  # noqa: S105
    mock_args_debug_true.func = MagicMock(return_value=0)

    mock_args_debug_false = MagicMock()
    mock_args_debug_false.configs = mock_configs_path
    mock_args_debug_false.debug = False
    mock_args_debug_false.token = "dummy_token"  # noqa: S105
    mock_args_debug_false.func = MagicMock(return_value=0)

    mock_logger = MagicMock()
    mock_logger.setLevel = MagicMock()

    with (
        patch("openqabot.args.ArgumentParser.parse_args", side_effect=[mock_args_debug_true, mock_args_debug_false]),
        patch("openqabot.main.create_logger", return_value=mock_logger),
        patch("sys.exit", side_effect=SystemExit),
        contextlib.suppress(SystemExit),
    ):
        main()
