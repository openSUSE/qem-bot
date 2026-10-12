# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Tests for the handle-submissions command."""

from pathlib import Path

from pytest_mock import MockerFixture
from typer.testing import CliRunner

from openqabot.args import app

runner = CliRunner()


def test_handle_submissions(mocker: MockerFixture, tmp_path: Path) -> None:
    bot = mocker.patch("openqabot.args.OpenQABot")
    bot.return_value.return_value = 0
    sync = mocker.patch("openqabot.args.SubResultsSync")
    sync.return_value.return_value = 0
    approve = mocker.patch("openqabot.args.Approver")
    approve.return_value.return_value = 0

    result = runner.invoke(
        app,
        ["--token", "foo", "--configs", str(tmp_path), "handle-submissions", "--ignore-onetime"],
    )

    assert result.exit_code == 0
    bot.assert_called_once()
    sync.assert_called_once()
    approve.assert_called_once()

    bot_args = bot.call_args[0][0]
    assert bot_args.ignore_onetime is True
    assert bot_args.disable_submissions is False
    assert bot_args.disable_aggregates is True
