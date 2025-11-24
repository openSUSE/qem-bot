# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

import contextlib
import logging
import sys
from unittest.mock import MagicMock, patch

import pytest

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


@patch("openqabot.args.ArgumentParser.parse_args")
def test_main_configs_not_dir_triggers_error_and_exit(
    mock_parse_args: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_configs_path = MagicMock()
    mock_configs_path.is_dir.return_value = False

    mock_args = MagicMock()
    mock_args.configs = mock_configs_path
    mock_args.token = "dummy_token"  # noqa: S105
    del mock_args.no_config
    mock_parse_args.return_value = mock_args

    mock_sys_exit = MagicMock(side_effect=SystemExit(1))
    monkeypatch.setattr(sys, "exit", mock_sys_exit)
    caplog.set_level(logging.ERROR)

    with pytest.raises(SystemExit) as excinfo:
        main()

    assert excinfo.value.code == 1
    mock_sys_exit.assert_called_once_with(1)
    assert "not a valid directory with config files" in caplog.text


def test_main_empty_argv_prints_help_and_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", [])
    mock_print_help = MagicMock()
    monkeypatch.setattr("openqabot.args.ArgumentParser.print_help", mock_print_help)
    mock_sys_exit = MagicMock(side_effect=SystemExit(0))
    monkeypatch.setattr(sys, "exit", mock_sys_exit)

    with pytest.raises(SystemExit) as excinfo:
        main()

    mock_print_help.assert_called_once()
    mock_sys_exit.assert_called_once_with(0)
    assert excinfo.value.code == 0


def test_main_debug_flag_sets_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_configs_path = MagicMock()
    mock_configs_path.is_dir.return_value = True

    mock_args = MagicMock()
    mock_args.configs = mock_configs_path
    mock_args.debug = True
    mock_args.token = "dummy_token"  # noqa: S105
    mock_args.func = MagicMock(return_value=0)
    monkeypatch.setattr("openqabot.args.ArgumentParser.parse_args", MagicMock(return_value=mock_args))
    mock_logger = MagicMock()
    mock_logger.setLevel = MagicMock()
    monkeypatch.setattr("openqabot.main.create_logger", MagicMock(return_value=mock_logger))
    monkeypatch.setattr(sys, "exit", MagicMock(side_effect=SystemExit))

    with contextlib.suppress(SystemExit):
        main()

    mock_logger.setLevel.assert_called_once_with(logging.DEBUG)

    mock_args.debug = False
    monkeypatch.setattr("openqabot.args.ArgumentParser.parse_args", MagicMock(return_value=mock_args))
    with contextlib.suppress(SystemExit):
        main()
