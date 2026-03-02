# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test args."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import typer
from typer.testing import CliRunner

from openqabot.args import app, main

if TYPE_CHECKING:
    import pytest
    from pytest_mock import MockerFixture

runner = CliRunner()


def test_full_run(mocker: MockerFixture, tmp_path: Path) -> None:
    bot = mocker.patch("openqabot.args.OpenQABot")
    bot.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "full-run"])
    assert result.exit_code == 0
    bot.assert_called_once()
    args = bot.call_args[0][0]
    assert not args.disable_aggregates
    assert not args.disable_submissions


def test_submission_schedule(mocker: MockerFixture, tmp_path: Path) -> None:
    bot = mocker.patch("openqabot.args.OpenQABot")
    bot.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "submissions-run"])
    assert result.exit_code == 0
    bot.assert_called_once()
    args = bot.call_args[0][0]
    assert args.disable_aggregates
    assert not args.disable_submissions


def test_updates_run(mocker: MockerFixture, tmp_path: Path) -> None:
    bot = mocker.patch("openqabot.args.OpenQABot")
    bot.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "updates-run"])
    assert result.exit_code == 0
    bot.assert_called_once()
    args = bot.call_args[0][0]
    assert not args.disable_aggregates
    assert args.disable_submissions


def test_sync_smelt(mocker: MockerFixture, tmp_path: Path) -> None:
    syncer = mocker.patch("openqabot.args.SMELTSync")
    syncer.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "smelt-sync"])
    assert result.exit_code == 0
    syncer.assert_called_once()


def test_sync_gitea(mocker: MockerFixture, tmp_path: Path) -> None:
    syncer = mocker.patch("openqabot.args.GiteaSync")
    syncer.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "gitea-sync"])
    assert result.exit_code == 0
    syncer.assert_called_once()


def test_sub_approve(mocker: MockerFixture, tmp_path: Path) -> None:
    approve = mocker.patch("openqabot.args.Approver")
    approve.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "sub-approve"])
    assert result.exit_code == 0
    approve.assert_called_once()


def test_sub_comment(mocker: MockerFixture, tmp_path: Path) -> None:
    comment = mocker.patch("openqabot.args.Commenter")
    comment.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "sub-comment"])
    assert result.exit_code == 0
    comment.assert_called_once()


def test_sub_sync_results(mocker: MockerFixture, tmp_path: Path) -> None:
    syncer = mocker.patch("openqabot.args.SubResultsSync")
    syncer.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "sub-sync-results"])
    assert result.exit_code == 0
    syncer.assert_called_once()


def test_aggr_sync_results(mocker: MockerFixture, tmp_path: Path) -> None:
    syncer = mocker.patch("openqabot.args.AggregateResultsSync")
    syncer.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "aggr-sync-results"])
    assert result.exit_code == 0
    syncer.assert_called_once()


def test_increment_approve(mocker: MockerFixture) -> None:
    approve = mocker.patch("openqabot.args.IncrementApprover")
    approve.return_value.return_value = 0
    # No config check needed for increment-approve
    result = runner.invoke(app, ["--token", "foo", "increment-approve"])
    assert result.exit_code == 0
    approve.assert_called_once()


def test_repo_diff(mocker: MockerFixture) -> None:
    repo_diff = mocker.patch("openqabot.args.RepoDiff")
    repo_diff.return_value.return_value = 0
    # No config check needed for repo-diff
    result = runner.invoke(app, ["--token", "foo", "repo-diff"])
    assert result.exit_code == 0
    repo_diff.assert_called_once()


def test_amqp(mocker: MockerFixture, tmp_path: Path) -> None:
    amqp = mocker.patch("openqabot.args.AMQP")
    amqp.return_value.return_value = 0
    # Test with explicit URL
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "amqp", "--url", "amqp://host"])
    assert result.exit_code == 0
    amqp.assert_called_once()
    assert amqp.call_args[0][0].url == "amqp://host"

    # Verify that the default AMQP URL is correctly resolved from configuration when not explicitly provided.
    amqp.reset_mock()
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "amqp"])
    assert result.exit_code == 0
    amqp.assert_called_once()
    assert amqp.call_args[0][0].url == "amqps://suse:suse@rabbit.suse.de"


def test_incidents_run(mocker: MockerFixture, tmp_path: Path) -> None:
    bot = mocker.patch("openqabot.args.OpenQABot")
    bot.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "incidents-run"])
    assert result.exit_code == 0
    bot.assert_called_once()
    args = bot.call_args[0][0]
    assert args.disable_aggregates
    assert not args.disable_submissions


def test_inc_approve(mocker: MockerFixture, tmp_path: Path) -> None:
    approve = mocker.patch("openqabot.args.Approver")
    approve.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "inc-approve"])
    assert result.exit_code == 0
    approve.assert_called_once()


def test_inc_comment(mocker: MockerFixture, tmp_path: Path) -> None:
    comment = mocker.patch("openqabot.args.Commenter")
    comment.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "inc-comment"])
    assert result.exit_code == 0
    comment.assert_called_once()


def test_inc_sync_results(mocker: MockerFixture, tmp_path: Path) -> None:
    syncer = mocker.patch("openqabot.args.SubResultsSync")
    syncer.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "inc-sync-results"])
    assert result.exit_code == 0
    syncer.assert_called_once()


def test_configs_non_existent_all_commands(
    mocker: MockerFixture, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    mocker.patch("pathlib.Path.exists", return_value=False)
    commands = [
        "full-run",
        "submissions-run",
        "updates-run",
        "smelt-sync",
        "gitea-sync",
        "sub-approve",
        "sub-comment",
        "sub-sync-results",
        "aggr-sync-results",
        "amqp",
    ]
    with caplog.at_level(logging.ERROR):
        for cmd in commands:
            result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), cmd])
            assert result.exit_code == 1
            assert "Configuration error" in caplog.text
            caplog.clear()


def test_command_help(mocker: MockerFixture) -> None:
    # This covers the 'if "--help" in sys.argv' check in main() callback
    mocker.patch("sys.argv", ["qem-bot", "full-run", "--help"])
    result = runner.invoke(app, ["full-run", "--help"])
    assert result.exit_code == 0
    assert "Full schedule for Maintenance Submissions" in result.stdout


def test_args_help_bypasses_mandatory_token(mocker: MockerFixture) -> None:
    ctx = MagicMock(spec=typer.Context)
    ctx.resilient_parsing = False
    ctx.help_option_names = ["--help", "-h"]
    mocker.patch("sys.argv", ["qem-bot", "--help"])

    result = main(
        ctx,
        configs=Path("/etc/openqabot"),
        dry=False,
        fake_data=False,
        dump_data=False,
        debug=False,
        token=None,
        gitea_token=None,
        openqa_instance="https://openqa.suse.de",
        singlearch=Path("/etc/openqabot/singlearch.yml"),
        retry=2,
    )
    assert result is None, "Successful early return is expected because help flags bypass the mandatory token check"


def test_configs_file_accepted(mocker: MockerFixture, tmp_path: Path) -> None:
    config_file = tmp_path / "config.yml"
    config_file.write_text("product: foo")

    bot = mocker.patch("openqabot.args.OpenQABot")
    bot.return_value.return_value = 0

    result = runner.invoke(app, ["--token", "foo", "--configs", str(config_file), "full-run"])

    assert result.exit_code == 0
    bot.assert_called_once()


def test_configs_dir_accepted(mocker: MockerFixture, tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()

    bot = mocker.patch("openqabot.args.OpenQABot")
    bot.return_value.return_value = 0

    result = runner.invoke(app, ["--token", "foo", "--configs", str(config_dir), "full-run"])

    assert result.exit_code == 0
    bot.assert_called_once()


def test_main_no_token_exit(mocker: MockerFixture) -> None:
    """Test that main exits with 1 when token is missing and help is not requested."""
    # Mock sys.argv to not contain any help options
    mocker.patch("sys.argv", ["qem-bot", "full-run"])

    # We need to invoke via runner to capture the SystemExit
    result = runner.invoke(app, ["full-run"])
    assert result.exit_code == 1
    assert (
        "Error: Missing option '--token' / '-t'." in result.stdout
        or "Error: Missing option '--token' / '-t'." in result.stderr
    )


def test_main_token_provided_no_help(mocker: MockerFixture, tmp_path: Path) -> None:
    """Test that application state is correctly initialized when a valid token is provided.

    Verifies that providing a token allows the application context to be fully established
    for subcommand execution.
    """
    bot = mocker.patch("openqabot.args.OpenQABot")
    bot.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "full-run"])
    assert result.exit_code == 0
