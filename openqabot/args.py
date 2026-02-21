# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Command line arguments parsing."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated
from urllib.parse import urlparse

import typer

import openqabot.config as config_module

from .aggrsync import AggregateResultsSync
from .amqp import AMQP
from .approver import Approver
from .commenter import Commenter
from .config import BUILD_REGEX
from .giteasync import GiteaSync
from .incrementapprover import IncrementApprover
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


@app.callback()
def main(  # noqa: PLR0913
    ctx: typer.Context,
    *,
    configs: Annotated[
        Path,
        typer.Option(
            "-c",
            "--configs",
            help="Directory or single file with openqabot configuration metadata",
            file_okay=True,
            dir_okay=True,
            readable=True,
        ),
    ] = Path("/etc/openqabot"),
    dry: Annotated[bool, typer.Option("--dry", help="Dry run, do not post any data")] = False,
    fake_data: Annotated[
        bool,
        typer.Option("--fake-data", help="Use fake data, do not query data from real services"),
    ] = False,
    dump_data: Annotated[
        bool,
        typer.Option("--dump-data", help="Dump requested data for later use via --fake-data"),
    ] = False,
    debug: Annotated[bool, typer.Option("-d", "--debug", help="Enable debug output")] = False,
    token: Annotated[
        str | None,
        typer.Option("-t", "--token", envvar="QEM_BOT_TOKEN", help="Token for qem dashboard api"),
    ] = None,
    gitea_token: Annotated[
        str | None,
        typer.Option("-g", "--gitea-token", help="Token for Gitea api"),
    ] = None,
    openqa_instance: Annotated[
        str,
        typer.Option(
            "-i",
            "--openqa-instance",
            help="The openQA instance to use\n Other instances than OSD do not update dashboard database",
        ),
    ] = "https://openqa.suse.de",
    singlearch: Annotated[
        Path,
        typer.Option(
            "-s",
            "--singlearch",
            help="Yaml config with list of singlearch packages for submissions run",
        ),
    ] = Path("/etc/openqabot/singlearch.yml"),
    retry: Annotated[int, typer.Option("-r", "--retry", help="Number of retries")] = 2,
) -> None:
    """QEM-Dashboard, SMELT, Gitea and openQA connector."""
    # Configure logging
    log_obj = create_logger("bot")
    if debug:
        log_obj.setLevel(logging.DEBUG)

    # Allow missing token if help was requested
    if token is None and not ctx.resilient_parsing:
        # Check if help is in the arguments
        if any(arg in sys.argv for arg in ctx.help_option_names):
            return

        print("Error: Missing option '--token' / '-t'.", file=sys.stderr)  # noqa: T201
        sys.exit(1)

    # Store global options in context
    ctx.obj = SimpleNamespace(
        configs=configs,
        dry=dry,
        fake_data=fake_data,
        dump_data=dump_data,
        debug=debug,
        token=token,
        gitea_token=gitea_token,
        openqa_instance=urlparse(openqa_instance),
        singlearch=singlearch,
        retry=retry,
    )


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
    args.ignore_onetime = ignore_onetime
    args.submission = submission
    args.disable_submissions = False
    args.disable_aggregates = False

    if not args.configs.is_dir():
        log.error("Configuration error: %s is not a valid directory", args.configs)
        sys.exit(1)

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
    args.ignore_onetime = ignore_onetime
    args.submission = submission
    args.disable_submissions = False
    args.disable_aggregates = True

    if not args.configs.is_dir():
        log.error("Configuration error: %s is not a valid directory", args.configs)
        sys.exit(1)

    bot = OpenQABot(args)
    sys.exit(bot())


@app.command("incidents-run", hidden=True)
def incidents_run(
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
    """DEPRECATED: Submissions only schedule for Maintenance Submissions in openQA (use submissions-run)."""  # noqa: D401
    submissions_run(ctx, ignore_onetime=ignore_onetime, submission=submission)


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
    args.ignore_onetime = ignore_onetime
    args.disable_aggregates = False
    args.disable_submissions = True

    if not args.configs.is_dir():
        log.error("Configuration error: %s is not a valid directory", args.configs)
        sys.exit(1)

    bot = OpenQABot(args)
    sys.exit(bot())


@app.command("smelt-sync")
def smelt_sync(ctx: typer.Context) -> None:
    """Sync data from SMELT into QEM Dashboard."""
    args = ctx.obj

    if not args.configs.is_dir():
        log.error("Configuration error: %s is not a valid directory", args.configs)
        sys.exit(1)

    syncer = SMELTSync(args)
    sys.exit(syncer())


@app.command("gitea-sync")
def gitea_sync(
    ctx: typer.Context,
    *,
    gitea_repo: Annotated[
        str, typer.Option("--gitea-repo", help="Repository on Gitea to check for PRs")
    ] = "products/SLFO",
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
    pr_number: Annotated[
        int | None,
        typer.Option(
            "--pr-number",
            help="Only consider the specified PR (for manual debugging)",
        ),
    ] = None,
) -> None:
    """Sync data from Gitea into QEM Dashboard."""
    args = ctx.obj
    args.gitea_repo = gitea_repo
    args.allow_build_failures = allow_build_failures
    args.consider_unrequested_prs = consider_unrequested_prs
    args.pr_number = pr_number

    if not args.configs.is_dir():
        log.error("Configuration error: %s is not a valid directory", args.configs)
        sys.exit(1)

    syncer = GiteaSync(args)
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
) -> None:
    """Approve submissions which passed tests."""
    args = ctx.obj
    args.all_submissions = all_submissions
    args.submission = submission
    args.incident = submission

    if not args.configs.is_dir():
        log.error("Configuration error: %s is not a valid directory", args.configs)
        sys.exit(1)

    approve = Approver(args)
    sys.exit(approve())


@app.command("inc-approve", hidden=True)
def inc_approve(
    ctx: typer.Context,
    *,
    all_submissions: Annotated[
        bool,
        typer.Option("--all-submissions", help="use all submissions without care about rrid"),
    ] = False,
    incident: Annotated[
        str | None,
        typer.Option(
            "-I",
            "--incident",
            help="Submission ID (to approve only a single submission)",
        ),
    ] = None,
) -> None:
    """DEPRECATED: Approve submissions which passed tests (use sub-approve)."""  # noqa: D401
    sub_approve(ctx, all_submissions=all_submissions, submission=incident)


@app.command("sub-comment")
def sub_comment(ctx: typer.Context) -> None:
    """Comment submissions in BuildService."""
    args = ctx.obj

    if not args.configs.is_dir():
        log.error("Configuration error: %s is not a valid directory", args.configs)
        sys.exit(1)

    comment = Commenter(args)
    sys.exit(comment())


@app.command("inc-comment", hidden=True)
def inc_comment(ctx: typer.Context) -> None:
    """DEPRECATED: Comment submissions in BuildService (use sub-comment)."""  # noqa: D401
    sub_comment(ctx)


@app.command("sub-sync-results")
def sub_sync_results(ctx: typer.Context) -> None:
    """Sync results of openQA submission jobs to Dashboard."""
    args = ctx.obj

    if not args.configs.is_dir():
        log.error("Configuration error: %s is not a valid directory", args.configs)
        sys.exit(1)

    syncer = SubResultsSync(args)
    sys.exit(syncer())


@app.command("inc-sync-results", hidden=True)
def inc_sync_results(ctx: typer.Context) -> None:
    """DEPRECATED: Sync results of openQA submission jobs to Dashboard (use sub-sync-results)."""  # noqa: D401
    sub_sync_results(ctx)


@app.command("aggr-sync-results")
def aggr_sync_results(ctx: typer.Context) -> None:
    """Sync results of openQA aggregate jobs to Dashboard."""
    args = ctx.obj

    if not args.configs.is_dir():
        log.error("Configuration error: %s is not a valid directory", args.configs)
        sys.exit(1)

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
    if url is not None:
        args.url = url
    else:
        # Default from settings (which was already loaded in main callback)
        args.url = config_module.settings.amqp_url

    if not args.configs.is_dir():
        log.error("Configuration error: %s is not a valid directory", args.configs)
        sys.exit(1)

    amqp_obj = AMQP(args)
    sys.exit(amqp_obj())
