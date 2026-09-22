# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test args."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
import typer
from typer.testing import CliRunner

from openqabot.args import GiteaSyncOptions, app, main
from openqabot.config import settings

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

runner = CliRunner()


@pytest.mark.parametrize(
    ("cmd", "mock_path", "disable_aggregates", "disable_submissions"),
    [
        ("full-run", "openqabot.args.OpenQABot", False, False),
        ("submissions-run", "openqabot.args.OpenQABot", True, False),
        ("updates-run", "openqabot.args.OpenQABot", False, True),
        (["advanced", "smelt-sync"], "openqabot.args.SMELTSync", None, None),
        (["advanced", "gitea-sync"], "openqabot.args.GiteaSync", None, None),
        ("gitea-trigger", "openqabot.args.GiteaTrigger", None, None),
        (["advanced", "sub-comment"], "openqabot.args.Commenter", None, None),
        ("sub-sync-results", "openqabot.args.SubResultsSync", None, None),
        ("aggr-sync-results", "openqabot.args.AggregateResultsSync", None, None),
        ("increment-approve", "openqabot.args.IncrementApprover", None, None),
        (["advanced", "repo-diff"], "openqabot.args.RepoDiff", None, None),
    ],
)
def test_command_success_exits(
    mocker: MockerFixture,
    tmp_path: Path,
    cmd: str | list[str],
    mock_path: str,
    *,
    disable_aggregates: bool | None,
    disable_submissions: bool | None,
) -> None:
    """Test that each command correctly exits with 0 and invokes the proper class on success."""
    if cmd == ["advanced", "sub-comment"]:
        mocker.patch("openqabot.args.get_submissions", return_value=[])

    config_file = tmp_path / "trigger.yml"
    config_file.write_text("trigger_config: []")

    mock_obj = mocker.patch(mock_path)
    mock_obj.return_value.return_value = 0

    cmd_args = cmd if isinstance(cmd, list) else [cmd]
    result = runner.invoke(app, ["--token", "foo", "--gitea-token", "bar", "--configs", str(tmp_path), *cmd_args])
    assert result.exit_code == 0
    mock_obj.assert_called_once()

    if disable_aggregates is not None:
        args = mock_obj.call_args[0][0]
        assert args.disable_aggregates is disable_aggregates
        assert args.disable_submissions is disable_submissions


def test_sync_gitea_passes_debug_options(mocker: MockerFixture, tmp_path: Path) -> None:
    syncer = mocker.patch("openqabot.args.GiteaSync")
    syncer.return_value.return_value = 0
    result = runner.invoke(
        app,
        [
            *["--token", "foo", "--gitea-token", "bar", "--configs", str(tmp_path)],
            *["advanced", "gitea-sync", "--gitea-project", "products/SLFO", "--pr-number", "42", "--amqp-only"],
            *["--amqp-url", "amqps://example.com"],
        ],
    )
    assert result.exit_code == 0
    args = syncer.call_args[0][0]
    assert args.gitea_project == ["products/SLFO"]
    assert args.pr_number == 42
    assert args.skip_initial_sync
    assert args.amqp_url == "amqps://example.com"


def test_sync(mocker: MockerFixture, tmp_path: Path) -> None:
    smelt = mocker.patch("openqabot.args.SMELTSync")
    smelt.return_value.return_value = 0
    gitea = mocker.patch("openqabot.args.GiteaSync")
    gitea.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--gitea-token", "bar", "--configs", str(tmp_path), "sync"])
    assert result.exit_code == 0
    smelt.assert_called_once()
    gitea.assert_called_once()
    args = gitea.call_args[0][0]
    assert args.gitea_project == ["products/SLFO", "products/SLFO_Kernel"]
    assert args.pr_number is None
    assert not args.amqp
    assert not args.skip_initial_sync
    assert args.amqp_url == "amqps://suse:suse@rabbit.suse.de"


def test_gitea_sync_options_defaults() -> None:
    options = GiteaSyncOptions()
    assert options.gitea_project == "products/SLFO,products/SLFO_Kernel"
    assert options.amqp_url == "amqps://suse:suse@rabbit.suse.de"
    assert not options.allow_build_failures
    assert not options.consider_unrequested_prs
    assert options.pr_number is None
    assert not options.amqp
    assert not options.skip_initial_sync


@pytest.mark.parametrize(
    ("extra_args", "env", "expected_comment"),
    [
        ([], {}, True),
        (["--no-comment"], {}, False),
        (["--comment"], {}, True),
        ([], {"QEM_BOT_APPROVE_COMMENT": "True"}, True),
    ],
)
def test_sub_approve(
    mocker: MockerFixture,
    tmp_path: Path,
    extra_args: list[str],
    env: dict[str, str],
    expected_comment: bool,  # ruff: ignore[boolean-type-hint-positional-argument]
) -> None:
    approve = mocker.patch("openqabot.args.Approver")
    approve.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "sub-approve", *extra_args], env=env)
    assert result.exit_code == 0
    approve.assert_called_once()
    assert approve.call_args[0][0].comment is expected_comment


def test_sub_comment_with_detailed_args(mocker: MockerFixture, tmp_path: Path) -> None:
    mocker.patch("openqabot.args.get_submissions", return_value=[])
    comment = mocker.patch("openqabot.args.Commenter")
    comment.return_value.return_value = 0
    result = runner.invoke(
        app,
        [
            "--token",
            "foo",
            "--configs",
            str(tmp_path),
            "advanced",
            "sub-comment",
            "--enable-detailed-comments",
            "--fallback-contact",
            "Test Contact",
            "--generic-tool-issues-contact",
            "@test",
            "--max-detailed-comment-entries",
            "5",
        ],
    )
    assert result.exit_code == 0
    comment.assert_called_once()


def test_increment_approve_with_detailed_args(mocker: MockerFixture, tmp_path: Path) -> None:
    approve = mocker.patch("openqabot.args.IncrementApprover")
    approve.return_value.return_value = 0
    result = runner.invoke(
        app,
        [
            "--token",
            "foo",
            "--configs",
            str(tmp_path),
            "increment-approve",
            "--enable-detailed-comments",
            "--fallback-contact",
            "Test Contact",
            "--generic-tool-issues-contact",
            "@test",
            "--max-detailed-comment-entries",
            "5",
        ],
    )
    assert result.exit_code == 0
    approve.assert_called_once()
    args = approve.call_args[0][0]
    assert args.enable_detailed_comments is True
    assert args.fallback_contact == "Test Contact"
    assert args.generic_tool_issues_contact == "@test"
    assert args.max_detailed_comment_entries == 5


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        (None, False),
        ("--consider-standalone-jobs", True),
        ("--no-consider-standalone-jobs", False),
    ],
)
def test_increment_approve_consider_standalone_jobs(
    mocker: MockerFixture,
    tmp_path: Path,
    flag: str | None,
    expected: bool,  # noqa: FBT001
) -> None:
    approve = mocker.patch("openqabot.args.IncrementApprover")
    approve.return_value.return_value = 0
    argv = ["--token", "foo", "--configs", str(tmp_path), "increment-approve"]
    if flag is not None:
        argv.append(flag)
    result = runner.invoke(app, argv)
    assert result.exit_code == 0
    approve.assert_called_once()
    assert approve.call_args[0][0].consider_standalone_jobs is expected


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


def test_configs_non_existent_all_commands(mocker: MockerFixture, tmp_path: Path) -> None:
    non_existent = tmp_path / "does_not_exist"
    mock_log = mocker.patch("openqabot.args.log")
    # We only need to test a few representative commands to ensure the config check in main() works.
    commands = [
        "full-run",
        "amqp",
    ]
    for cmd in commands:
        result = runner.invoke(app, ["--token", "foo", "--configs", str(non_existent), cmd])
        assert result.exit_code == 1
        mock_log.error.assert_called()
        error_msg = mock_log.error.call_args[0][0]
        assert "Configuration error" in error_msg
        mock_log.reset_mock()


def test_command_help(mocker: MockerFixture) -> None:
    # This covers the 'if "--help" in sys.argv' check in main() callback
    mocker.patch("sys.argv", ["qem-bot", "full-run", "--help"])
    # Avoid full runner.invoke if we just want to check help bypass logic
    # But we also want to ensure help is formatted correctly.
    # We use a mocked OpenQABot to ensure it's NOT called.
    mocker.patch("pathlib.Path.exists", return_value=True)
    bot = mocker.patch("openqabot.args.OpenQABot")
    result = runner.invoke(app, ["full-run", "--help"])
    assert result.exit_code == 0
    assert "Full schedule for Maintenance Submissions" in result.stdout
    bot.assert_not_called()


def test_args_help_bypasses_mandatory_token(mocker: MockerFixture) -> None:
    ctx = MagicMock(spec=typer.Context)
    ctx.resilient_parsing = False
    ctx.help_option_names = ["--help", "-h"]
    mocker.patch("sys.argv", ["qem-bot", "--help"])
    mocker.patch("pathlib.Path.exists", return_value=True)

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


def test_main_no_token_exit(mocker: MockerFixture, tmp_path: Path) -> None:
    """Test that main exits with 1 when token is missing and help is not requested."""
    # Mock sys.argv to not contain any help options and clear env to avoid token leakage
    mocker.patch.dict("os.environ", {}, clear=True)
    mocker.patch("sys.argv", ["qem-bot", "full-run"])

    # We need to invoke via runner to capture the SystemExit
    result = runner.invoke(app, ["--configs", str(tmp_path), "full-run"])
    assert result.exit_code == 1
    assert "Error: Missing option '--token' / '-t'." in result.output


@pytest.mark.parametrize(
    "command",
    [
        pytest.param(["advanced", "gitea-sync"], id="advanced gitea-sync rejects missing gitea token"),
        pytest.param(["sync"], id="sync rejects missing gitea token before running the SMELT sync"),
    ],
)
def test_main_no_gitea_token_exit_sync(mocker: MockerFixture, tmp_path: Path, command: list[str]) -> None:
    mocker.patch.dict("os.environ", {}, clear=True)
    smelt = mocker.patch("openqabot.args.SMELTSync")
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), *command])
    assert result.exit_code == 1
    assert "Error: Missing option '--gitea-token' / '-g' or environment variable QEM_BOT_GITEA_TOKEN." in result.output
    smelt.assert_not_called()


def test_main_no_gitea_token_exit_trigger(mocker: MockerFixture, tmp_path: Path) -> None:
    """Test that gitea-trigger exits with 1 when gitea_token is missing."""
    mocker.patch.dict("os.environ", {}, clear=True)
    config_file = tmp_path / "trigger.yml"
    config_file.write_text("trigger_config: []")
    result = runner.invoke(app, ["--configs", str(tmp_path), "gitea-trigger"])
    assert result.exit_code == 1
    assert "Error: Missing option '--gitea-token' / '-g' or environment variable QEM_BOT_GITEA_TOKEN." in result.output


def test_main_token_provided_no_help(mocker: MockerFixture, tmp_path: Path) -> None:
    """Test that application state is correctly initialized when a valid token is provided.

    Verifies that providing a token allows the application context to be fully established
    for subcommand execution.
    """
    bot = mocker.patch("openqabot.args.OpenQABot")
    bot.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "full-run"])
    assert result.exit_code == 0


def test_debug_flag(mocker: MockerFixture, tmp_path: Path) -> None:
    """Verify that --debug flag sets logger level to DEBUG."""
    mocker.patch("openqabot.args.OpenQABot").return_value.return_value = 0
    # Capture the logger used in args.py
    logger = logging.getLogger("bot")
    original_level = logger.level

    try:
        result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "--debug", "full-run"])
        assert result.exit_code == 0
        assert logger.level == logging.DEBUG
    finally:
        logger.setLevel(original_level)


def test_main_fake_data(mocker: MockerFixture, tmp_path: Path) -> None:
    """Test that mock responses are set up when --fake-data is provided."""
    setup_mock = mocker.patch("openqabot.args.setup_mock_responses")
    bot = mocker.patch("openqabot.args.OpenQABot")
    bot.return_value.return_value = 0
    result = runner.invoke(app, ["--fake-data", "--token", "foo", "--configs", str(tmp_path), "full-run"])
    assert result.exit_code == 0
    setup_mock.assert_called_once()


def test_config_yml_feeds_settings_and_context(mocker: MockerFixture, tmp_path: Path) -> None:
    """config.yml values reach settings and the subcommand context; error handling covered in test_config."""
    (tmp_path / "config.yml").write_text("OPENQA_INSTANCE: https://yaml.openqa.org\nQEM_BOT_RETRY: 7\n")
    bot = mocker.patch("openqabot.args.OpenQABot")
    bot.return_value.return_value = 0
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "full-run"])
    assert result.exit_code == 0
    assert settings.openqa_instance == "https://yaml.openqa.org"
    assert settings.retry == 7
    assert bot.call_args[0][0].retry == 7


def test_cli_options_override_config_yml(mocker: MockerFixture, tmp_path: Path) -> None:
    """Explicit CLI options take precedence over config.yml and update settings."""
    (tmp_path / "config.yml").write_text("OPENQA_INSTANCE: https://yaml.openqa.org\n")
    bot = mocker.patch("openqabot.args.OpenQABot")
    bot.return_value.return_value = 0
    result = runner.invoke(
        app,
        [
            "--token",
            "foo",
            "--configs",
            str(tmp_path),
            "--insecure",
            "--dry",
            "-i",
            "https://override.openqa",
            "full-run",
        ],
    )
    assert result.exit_code == 0
    assert settings.insecure is True
    assert settings.dry is True
    assert settings.openqa_instance == "https://override.openqa"


def test_gitea_sync_pr_number_with_multiple_projects(tmp_path: Path) -> None:
    """Test that gitea-sync exits with 1 when multiple projects are provided with a PR number."""
    result = runner.invoke(
        app,
        [
            "--token",
            "foo",
            "--gitea-token",
            "bar",
            "--configs",
            str(tmp_path),
            "advanced",
            "gitea-sync",
            "--gitea-project",
            "p1,p2",
            "--pr-number",
            "123",
        ],
    )
    assert result.exit_code == 1
    assert "Error: Option '--pr-number' requires a single project via '--gitea-project'." in result.output


@pytest.mark.parametrize(
    ("cmd", "mock_path"),
    [
        ("full-run", "openqabot.args.OpenQABot"),
        ("submissions-run", "openqabot.args.OpenQABot"),
        ("updates-run", "openqabot.args.OpenQABot"),
        ("sync", "openqabot.args.SMELTSync"),
        (["advanced", "smelt-sync"], "openqabot.args.SMELTSync"),
        (["advanced", "gitea-sync"], "openqabot.args.GiteaSync"),
        ("gitea-trigger", "openqabot.args.GiteaTrigger"),
        ("sub-approve", "openqabot.args.Approver"),
        (["advanced", "sub-comment"], "openqabot.args.Commenter"),
        ("sub-sync-results", "openqabot.args.SubResultsSync"),
        ("aggr-sync-results", "openqabot.args.AggregateResultsSync"),
        ("increment-approve", "openqabot.args.IncrementApprover"),
        (["advanced", "repo-diff"], "openqabot.args.RepoDiff"),
        ("amqp", "openqabot.args.AMQP"),
    ],
)
def test_command_failure_exits(mocker: MockerFixture, tmp_path: Path, cmd: str | list[str], mock_path: str) -> None:
    """Test that each command correctly exits with 1 when it fails."""
    if cmd == ["advanced", "sub-comment"]:
        mocker.patch("openqabot.args.get_submissions", return_value=[])

    config_file = tmp_path / "trigger.yml"
    config_file.write_text("trigger_config: []")

    mock_obj = mocker.patch(mock_path)
    mock_obj.return_value.return_value = 1

    cmd_args = cmd if isinstance(cmd, list) else [cmd]
    result = runner.invoke(app, ["--token", "foo", "--gitea-token", "bar", "--configs", str(tmp_path), *cmd_args])
    assert result.exit_code == 1
    mock_obj.assert_called_once()


def test_command_chaining_success(mocker: MockerFixture, tmp_path: Path) -> None:
    """Test executing multiple commands sequentially when they all succeed."""
    bot = mocker.patch("openqabot.args.OpenQABot")
    bot.return_value.return_value = 0

    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "full-run", "submissions-run"])
    assert result.exit_code == 0
    assert bot.call_count == 2


def test_command_chaining_fail_fast(mocker: MockerFixture, tmp_path: Path) -> None:
    """Test executing multiple commands sequentially halts on first failure."""
    bot = mocker.patch("openqabot.args.OpenQABot")
    bot.side_effect = [1, 0]

    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path), "full-run", "submissions-run"])
    assert result.exit_code == 1
    bot.assert_called_once()


def test_command_chaining_missing_command(tmp_path: Path) -> None:
    """Test that calling the app with options but no command fails with "Missing command."."""
    result = runner.invoke(app, ["--token", "foo", "--configs", str(tmp_path)])
    assert result.exit_code == 2
    assert "Missing command." in result.output
