# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

import logging
import sys
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from openqabot.main import main  # SUT


def test_help(mocker: MockerFixture) -> None:
    mocker.patch.object(sys, "argv", ["--help"])
    with pytest.raises(SystemExit):
        main()


def test_no_args_prints_help(mocker: MockerFixture) -> None:
    mocker.patch.object(sys, "argv", [])
    mocker.patch("openqabot.args.ArgumentParser.print_help")
    with pytest.raises(SystemExit):
        main()


def test_main_configs_not_dir_triggers_error_and_exit(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mock_configs_path = mocker.Mock()
    mock_configs_path.is_dir.return_value = False
    mock_args = mocker.Mock()
    mock_args.configs = mock_configs_path
    del mock_args.no_config
    mocker.patch("openqabot.args.ArgumentParser.parse_args", return_value=mock_args)
    sys_exit_spy = mocker.spy(sys, "exit")
    with pytest.raises(SystemExit):
        main()
    sys_exit_spy.assert_called_once_with(1)
    assert "Configuration error" in caplog.text
    assert "is not a valid directory" in caplog.text


def test_main_debug_flag_sets_log_level(mocker: MockerFixture) -> None:
    mock_configs_path = mocker.Mock()
    mock_configs_path.is_dir.return_value = True

    mock_logger = mocker.Mock()
    mock_logger.setLevel = mocker.Mock()
    mocker.patch("openqabot.main.create_logger", return_value=mock_logger)
    mock_args = mocker.Mock()
    mock_args.configs = mock_configs_path
    mock_args.token = "dummy_token"  # noqa: S105
    mock_args.func = mocker.Mock(return_value=0)
    mock_args.debug = True
    mocker.patch("openqabot.args.ArgumentParser.parse_args", return_value=mock_args)
    with pytest.raises(SystemExit):
        main()
    mock_logger.setLevel.assert_called_once_with(logging.DEBUG)
    mock_args.debug = False
    mocker.patch("openqabot.args.ArgumentParser.parse_args", return_value=mock_args)
    with pytest.raises(SystemExit):
        main()


def test_main_keyboard_interrupt(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.main.create_logger")
    mock_args = MagicMock()
    mock_args.configs.is_dir.return_value = True
    mock_args.debug = False
    mock_args.func.side_effect = KeyboardInterrupt
    mock_parser = MagicMock(parse_args=MagicMock(return_value=mock_args))
    mocker.patch("openqabot.main.get_parser", return_value=mock_parser)
    mock_exit = mocker.patch("sys.exit")
    mocker.patch("sys.argv", ["qem-bot", "full-run"])
    main()
    mock_exit.assert_called_with(1)
