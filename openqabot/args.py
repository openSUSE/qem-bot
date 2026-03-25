# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Command line arguments parsing."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import typer

import openqabot.config as config_module

from .aggrsync import AggregateResultsSync
from .amqp import AMQP
from .approver import Approver
from .commenter import Commenter
from .config import BUILD_REGEX
from .giteasync import GiteaSync
from .giteatrigger import GiteaTrigger
from .incrementapprover import IncrementApprover
from .loader.qem import get_submissions
from .openqabot import OpenQABot
from .repodiff import RepoDiff
from .smeltsync import SMELTSync
from .subsyncres import SubResultsSync
from .utils import create_logger

app = typer.Typer(
    name="qem-bot",
    help="QEM-Dashboard, SMELT, Gitea and openQA connector",
    no_args_is_help=True,
    add_completion=False,
)
log = logging.getLogger("bot")

pr_number_arg = Annotated[
    int | None,
    typer.Option(
        "--pr-number",
        help="Only consider the specified PR (for manual debugging)",
    ),
]
gitea_repo_arg = Annotated[str, typer.Option("--gitea-repo", help="Repository on Gitea to check for PRs")]

comment_option = Annotated[
    bool,
    typer.Option(
        "--comment/--no-comment",
        envvar="QEM_BOT_APPROVE_COMMENT",
        help="Post a comment on OBS/Gitea when a submission is not approved",
    ),
]


def _require_token(args: SimpleNamespace) -> None:
    """Enforce that a qem-dashboard token is present before entering a command.

    Call this guard at the start of every command that does need the dashboard.
    Used in the most `qem-bot` subcommands which use the qem-dashboard API,
    which requires Bearer token authentication. The token
    is intentionally optional, in case of dashboard-free commands.
    """
    if args.token is None:
        typer.echo("Error: Missing option '--token' / '-t'.", err=True)
        raise typer.Exit(1)


@app.callback()
def main(  # noqa: PLR0913
    ctx: typer.Context,
    *,
    configs: Annotated[
        Path,
        typer.Option(
            "-c",
            "--configs",
            envvar="QEM_BOT_CONFIGS",
            help="Directory or single file with openqabot configuration metadata",
            file_okay=True,
            dir_okay=True,
            readable=True,
        ),
    ] = Path("/etc/openqabot"),
    dry: Annotated[bool, typer.Option("--dry", envvar="QEM_BOT_DRY", help="Dry run, do not post any data")] = False,
    fake_data: Annotated[
        bool,
        typer.Option(
            "--fake-data",
            envvar="QEM_BOT_FAKE_DATA",
            help="Use fake data, do not query data from real services",
        ),
    ] = False,
    dump_data: Annotated[
        bool,
        typer.Option(
            "--dump-data",
            envvar="QEM_BOT_DUMP_DATA",
            help="Dump requested data for later use via --fake-data",
        ),
    ] = False,
    debug: Annotated[bool, typer.Option("-d", "--debug", envvar="QEM_BOT_DEBUG", help="Enable debug output")] = False,
    insecure: Annotated[
        bool,
        typer.Option(
            "--insecure/--no-insecure",
            envvar="QEM_BOT_INSECURE",
            help="Disable TLS verification for all API calls",
        ),
    ] = False,
    token: Annotated[
        str | None,
        typer.Option("-t", "--token", envvar="QEM_BOT_TOKEN", help="Token for qem dashboard api"),
    ] = None,
    gitea_token: Annotated[
        str | None,
        typer.Option("-g", "--gitea-token", envvar="QEM_BOT_GITEA_TOKEN", help="Token for Gitea api"),
    ] = None,
    openqa_instance: Annotated[
        str,
        typer.Option(
            "-i",
            "--openqa-instance",
            envvar="OPENQA_INSTANCE",
            help="The openQA instance to use\n Other instances than OSD do not update dashboard database",
        ),
    ] = "https://openqa.suse.de",
    singlearch: Annotated[
        Path,
        typer.Option(
            "-s",
            "--singlearch",
            envvar="QEM_BOT_SINGLEARCH",
            help="Yaml config with list of singlearch packages for submissions run",
        ),
    ] = Path("/etc/openqabot/singlearch.yml"),
    retry: Annotated[int, typer.Option("-r", "--retry", envvar="QEM_BOT_RETRY", help="Number of retries")] = 2,
) -> None:
    """QEM-Dashboard, SMELT, Gitea and openQA connector."""
    # Configure logging
    log_obj = create_logger("bot")
    if debug:
        log_obj.setLevel(logging.DEBUG)

    # Update global configuration
    config_module.settings.insecure = insecure

    # Check if help is in the arguments
    if any(arg in sys.argv for arg in ctx.help_option_names):
        return

    if not configs.exists():
        log.error("Configuration error: %s does not exist", configs)
        sys.exit(1)

    # Store global options in context
    ctx.obj = SimpleNamespace(
        configs=configs,
        dry=dry,
        fake_data=fake_data,
        dump_data=dump_data,
        debug=debug,
        insecure=insecure,
        token=token,
        gitea_token=gitea_token,
        singlearch=singlearch,
        retry=retry,
    )

    config_module.settings.openqa_instance = openqa_instance
    config_module.settings.dry = dry
    config_module.settings.token = token


@app.command()
def full_run(
    ctx: typer.Context,
    *,
    ignore_onetime: Annotated[
        bool,
        typer.Option("-i", "--ignore-onetime", help="Ignore onetime and schedule those test runs"),
    ] = False,
    submission: Annotated[
        str | None,
        typer.Option(
            "-I",
            "--submission",
            help="Submission ID (to process only a single submission)",
        ),
    ] = None,
) -> None:
    """Full schedule for Maintenance Submissions in openQA."""
    args = ctx.obj
    _require_token(args)
    args.ignore_onetime = ignore_onetime
    args.submission = submission
    args.disable_submissions = False
    args.disable_aggregates = False

    bot = OpenQABot(args)
    sys.exit(bot())


@app.command("submissions-run")
def submissions_run(
    ctx: typer.Context,
    *,
    ignore_onetime: Annotated[
        bool,
        typer.Option("-i", "--ignore-onetime", help="Ignore onetime and schedule those test runs"),
    ] = False,
    submission: Annotated[
        str | None,
        typer.Option(
            "-I",
            "--submission",
            help="Submission ID (to process only a single submission)",
        ),
    ] = None,
) -> None:
    """Submissions only schedule for Maintenance Submissions in openQA."""
    args = ctx.obj
    _require_token(args)
    args.ignore_onetime = ignore_onetime
    args.submission = submission
    args.disable_submissions = False
    args.disable_aggregates = True

    bot = OpenQABot(args)
    sys.exit(bot())


@app.command("updates-run")
def updates_run(
    ctx: typer.Context,
    *,
    ignore_onetime: Annotated[
        bool,
        typer.Option("-i", "--ignore-onetime", help="Ignore onetime and schedule those test runs"),
    ] = False,
) -> None:
    """Aggregates only schedule for Maintenance Submissions in openQA."""  # noqa: D401
    args = ctx.obj
    _require_token(args)
    args.ignore_onetime = ignore_onetime
    args.disable_aggregates = False
    args.disable_submissions = True

    bot = OpenQABot(args)
    sys.exit(bot())


@app.command("smelt-sync")
def smelt_sync(ctx: typer.Context) -> None:
    """Sync data from SMELT into QEM Dashboard."""
    args = ctx.obj
    _require_token(args)

    syncer = SMELTSync(args)
    sys.exit(syncer())


@app.command("gitea-sync")
def gitea_sync(  # noqa: PLR0913
    ctx: typer.Context,
    *,
    gitea_repo: gitea_repo_arg = "products/SLFO",
    allow_build_failures: Annotated[
        bool,
        typer.Option("--allow-build-failures", help="Sync data from PRs despite failing packages"),
    ] = False,
    consider_unrequested_prs: Annotated[
        bool,
        typer.Option(
            "--consider-unrequested-prs",
            help=f"Consider PRs where no review from team {config_module.settings.obs_group} was requested as well",
        ),
    ] = False,
    pr_number: pr_number_arg = None,
    amqp: Annotated[
        bool,
        typer.Option(
            "--amqp",
            help="After initial sync listen for new PRs via AMQP and submit them to QEM dashboard immediately",
        ),
    ] = False,
    amqp_url: Annotated[str | None, typer.Option("--amqp-url", help="the URL of the AMQP server")] = None,
    skip_initial_sync: Annotated[
        bool,
        typer.Option(
            "--amqp-only",
            help="Skip initial sync before handling AMQP events for new PRs",
        ),
    ] = False,
) -> None:
    """Sync data from Gitea into QEM Dashboard."""
    args = ctx.obj
    _require_token(args)
    args.gitea_repo = gitea_repo
    args.allow_build_failures = allow_build_failures
    args.consider_unrequested_prs = consider_unrequested_prs
    args.pr_number = pr_number
    args.amqp = amqp
    # Default from settings (which was already loaded in main callback)
    args.amqp_url = amqp_url if amqp_url is not None else config_module.settings.amqp_url
    args.skip_initial_sync = skip_initial_sync

    syncer = GiteaSync(args)
    sys.exit(syncer())


@app.command("gitea-trigger")
def gitea_trigger(
    ctx: typer.Context,
    *,
    gitea_repo: gitea_repo_arg = "products/SLFO",
    pr_label: Annotated[
        str,
        typer.Option("--pr-label", envvar="PR_LABEL", help="Gitea PRs label for which to trigger tests"),
    ] = "staging/In Progress",
    pr_number: pr_number_arg = None,
    comment: comment_option = True,
) -> None:
    """Trigger testing for PR(s) with certain label."""
    args = ctx.obj
    args.gitea_repo = gitea_repo
    args.pr_number = pr_number
    args.pr_label = pr_label
    args.comment = comment

    syncer = GiteaTrigger(args)
    sys.exit(syncer())


@app.command("sub-approve")
def sub_approve(
    ctx: typer.Context,
    *,
    all_submissions: Annotated[
        bool,
        typer.Option("--all-submissions", help="use all submissions without care about rrid"),
    ] = False,
    submission: Annotated[
        str | None,
        typer.Option(
            "-I",
            "--submission",
            help="Submission ID (to approve only a single submission)",
        ),
    ] = None,
    comment: comment_option = True,
) -> None:
    """Approve submissions which passed tests."""
    args = ctx.obj
    _require_token(args)
    args.all_submissions = all_submissions
    args.submission = submission
    args.incident = submission
    args.comment = comment

    approve = Approver(args)
    sys.exit(approve())


@app.command("sub-comment")
def sub_comment(ctx: typer.Context) -> None:
    """Comment submissions in BuildService."""
    args = ctx.obj
    _require_token(args)

    submissions = get_submissions()
    comment = Commenter(args, submissions)
    sys.exit(comment())


@app.command("sub-sync-results")
def sub_sync_results(ctx: typer.Context) -> None:
    """Sync results of openQA submission jobs to Dashboard."""
    args = ctx.obj
    _require_token(args)

    syncer = SubResultsSync(args)
    sys.exit(syncer())


@app.command("aggr-sync-results")
def aggr_sync_results(ctx: typer.Context) -> None:
    """Sync results of openQA aggregate jobs to Dashboard."""
    args = ctx.obj
    _require_token(args)

    syncer = AggregateResultsSync(args)
    sys.exit(syncer())


@app.command("increment-approve")
def increment_approve(  # noqa: PLR0913
    ctx: typer.Context,
    *,
    project_base: Annotated[
        str, typer.Option("--project-base", help="The base for projects on OBS")
    ] = "SUSE:SLFO:Products:SLES:16.0",
    build_project_suffix: Annotated[
        str,
        typer.Option(
            "--build-project-suffix",
            help="The project on OBS to monitor. Schedule jobs for (if --schedule is specified) and approve (if all tests passed)",  # noqa: E501
        ),
    ] = "TEST",
    diff_project_suffix: Annotated[
        str,
        typer.Option(
            "--diff-project-suffix",
            help="The project on OBS to compute a package diff to",
        ),
    ] = "PUBLISH/product",
    distri: Annotated[
        str,
        typer.Option(
            "--distri",
            help="Monitor and schedule only products with the specified DISTRI parameter",
        ),
    ] = "sle",
    version: Annotated[
        str,
        typer.Option(
            "--version",
            help="Monitor and schedule only products with the specified VERSION parameter",
        ),
    ] = "any",
    flavor: Annotated[
        str,
        typer.Option(
            "--flavor",
            help="Monitor and schedule only products with the specified FLAVOR parameter",
        ),
    ] = "any",
    schedule: Annotated[
        bool,
        typer.Option(
            "--schedule",
            help="Schedule a new product (if none exists or if the most recent product has no jobs)",
        ),
    ] = False,
    reschedule: Annotated[
        bool,
        typer.Option(
            "--reschedule",
            help="Always schedule a new product (even if one already exists)",
        ),
    ] = False,
    accepted: Annotated[
        bool,
        typer.Option("--accepted", help="Consider accepted product increment requests as well"),
    ] = False,
    request_id: Annotated[
        int | None,
        typer.Option(
            "--request-id",
            help="Check/approve the specified request (instead of the most recent one)",
        ),
    ] = None,
    build_listing_sub_path: Annotated[
        str,
        typer.Option(
            "--build-listing-sub-path",
            help="The sub path of the file listing used to determine BUILD and other parameters",
        ),
    ] = "product",
    build_regex: Annotated[
        str,
        typer.Option(
            "--build-regex",
            help="The regex used to determine BUILD and other parameters from the file listing",
        ),
    ] = BUILD_REGEX,
    product_regex: Annotated[
        str,
        typer.Option("--product-regex", help="The regex used to determine what products are relevant"),
    ] = "^SLE.*",
    increment_config: Annotated[
        Path | None,
        typer.Option(
            "--increment-config",
            help="Use configuration from the specified YAML document instead of arguments",
        ),
    ] = None,
) -> None:
    """Approve the most recent product increment for an OBS project if tests passed."""
    args = ctx.obj
    _require_token(args)
    args.project_base = project_base
    args.build_project_suffix = build_project_suffix
    args.diff_project_suffix = diff_project_suffix
    args.distri = distri
    args.version = version
    args.flavor = flavor
    args.schedule = schedule
    args.reschedule = reschedule
    args.accepted = accepted
    args.request_id = request_id
    args.build_listing_sub_path = build_listing_sub_path
    args.build_regex = build_regex
    args.product_regex = product_regex
    args.increment_config = increment_config

    approve = IncrementApprover(args)
    sys.exit(approve())


@app.command("repo-diff")
def repo_diff(
    ctx: typer.Context,
    *,
    repo_a: Annotated[
        str, typer.Option("--repo-a", help="The first repository")
    ] = "SUSE:SLFO:Products:SLES:16.0:TEST/product",
    repo_b: Annotated[
        str, typer.Option("--repo-b", help="The second repository")
    ] = "SUSE:SLFO:Products:SLES:16.0:PUBLISH/product",
) -> None:
    """Computes the diff between two repositories."""  # noqa: D401
    args = ctx.obj
    args.repo_a = repo_a
    args.repo_b = repo_b

    repo_diff_obj = RepoDiff(args)
    sys.exit(repo_diff_obj())


@app.command("amqp")
def amqp_cmd(
    ctx: typer.Context,
    *,
    url: Annotated[str | None, typer.Option("--url", help="the URL of the AMQP server")] = None,
) -> None:
    """AMQP listener daemon."""
    args = ctx.obj
    _require_token(args)
    if url is not None:
        args.url = url
    else:
        # Default from settings (which was already loaded in main callback)
        args.url = config_module.settings.amqp_url

    amqp_obj = AMQP(args)
    sys.exit(amqp_obj())
