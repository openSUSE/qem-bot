# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import ArgumentParser, Namespace
from pathlib import Path
from urllib.parse import urlparse

from . import AMQP_URL, BUILD_REGEX, OBS_GROUP


def do_full_schedule(args: Namespace) -> int:
    from .openqabot import OpenQABot

    args.disable_incidents = False
    args.disable_aggregates = False

    bot = OpenQABot(args)
    return bot()


def do_incident_schedule(args: Namespace) -> int:
    from .openqabot import OpenQABot

    args.disable_incidents = False
    args.disable_aggregates = True

    bot = OpenQABot(args)
    return bot()


def do_aggregate_schedule(args: Namespace) -> int:
    from .openqabot import OpenQABot

    args.disable_aggregates = False
    args.disable_incidents = True

    bot = OpenQABot(args)
    return bot()


def do_sync_smelt(args: Namespace) -> int:
    from .smeltsync import SMELTSync

    syncer = SMELTSync(args)
    return syncer()


def do_sync_gitea(args: Namespace) -> int:
    from .giteasync import GiteaSync

    syncer = GiteaSync(args)
    return syncer()


def do_approve(args: Namespace) -> int:
    from .approver import Approver

    approve = Approver(args)
    return approve()


def do_comment(args: Namespace) -> int:
    from .commenter import Commenter

    comment = Commenter(args)
    return comment()


def do_sync_inc_results(args: Namespace) -> int:
    from .incsyncres import IncResultsSync

    syncer = IncResultsSync(args)
    return syncer()


def do_sync_aggregate_results(args: Namespace) -> int:
    from .aggrsync import AggregateResultsSync

    syncer = AggregateResultsSync(args)
    return syncer()


def do_increment_approve(args: Namespace) -> int:
    from .incrementapprover import IncrementApprover

    approve = IncrementApprover(args)
    return approve()


def do_repo_diff_computation(args: Namespace) -> int:
    from .repodiff import RepoDiff

    repo_diff = RepoDiff(args)
    return repo_diff()


def do_amqp(args: Namespace) -> int:
    from .amqp import AMQP

    amqp = AMQP(args)
    return amqp()


def get_parser() -> ArgumentParser:
    parser = ArgumentParser(description="QEM-Dashboard, SMELT, Gitea and openQA connector", prog="qem-bot")

    parser.add_argument(
        "-c",
        "--configs",
        type=Path,
        default=Path("/etc/openqabot"),
        help="Directory or single file with openqabot configuration metadata",
    )

    parser.add_argument("--dry", action="store_true", help="Dry run, do not post any data")
    parser.add_argument(
        "--fake-data",
        action="store_true",
        help="Use fake data, do not query data from real services",
    )
    parser.add_argument(
        "--dump-data",
        action="store_true",
        help="Dump requested data for later use via --fake-data",
    )

    parser.add_argument("-d", "--debug", action="store_true", help="Enable debug output")

    parser.add_argument("-t", "--token", required=True, type=str, help="Token for qem dashboard api")
    parser.add_argument("-g", "--gitea-token", required=False, type=str, help="Token for Gitea api")

    parser.add_argument(
        "-i",
        "--openqa-instance",
        type=urlparse,
        default=urlparse("https://openqa.suse.de"),
        help="The openQA instance to use\n Other instances than OSD do not update dashboard database",
    )

    parser.add_argument(
        "-s",
        "--singlearch",
        type=Path,
        default=Path("/etc/openqabot/singlearch.yml"),
        help="Yaml config with list of singlearch packages for incidents run",
    )

    parser.add_argument("-r", "--retry", type=int, default=2, help="Number of retries")

    commands = parser.add_subparsers()

    cmdfull = commands.add_parser("full-run", help="Full schedule for Maintenance Incidents in openQA")
    cmdfull.add_argument(
        "-i",
        "--ignore-onetime",
        action="store_true",
        help="Ignore onetime and schedule those test runs",
    )
    cmdfull.set_defaults(func=do_full_schedule)

    cmdinc = commands.add_parser(
        "incidents-run",
        help="Incidents only schedule for Maintenance Incidents in openQA",
    )
    cmdinc.add_argument(
        "-i",
        "--ignore-onetime",
        action="store_true",
        help="Ignore onetime and schedule those test runs",
    )
    cmdinc.set_defaults(func=do_incident_schedule)

    cmdupd = commands.add_parser("updates-run", help="updates only schedule for Maintenance Incidents in openQA")
    cmdupd.add_argument(
        "-i",
        "--ignore-onetime",
        action="store_true",
        help="Ignore onetime and schedule those test runs",
    )
    cmdupd.set_defaults(func=do_aggregate_schedule)

    cmdsync = commands.add_parser("smelt-sync", help="Sync data from SMELT into QEM Dashboard")
    cmdsync.set_defaults(func=do_sync_smelt)

    cmdgiteasync = commands.add_parser("gitea-sync", help="Sync data from Gitea into QEM Dashboard")
    cmdgiteasync.add_argument(
        "--gitea-repo",
        required=False,
        type=str,
        default="products/SLFO",
        help="Repository on Gitea to check for PRs",
    )
    cmdgiteasync.add_argument(
        "--allow-build-failures",
        action="store_true",
        help="Sync data from PRs despite failing packages",
    )
    cmdgiteasync.add_argument(
        "--consider-unrequested-prs",
        action="store_true",
        help="Consider PRs where no review from team %s was requested as well" % OBS_GROUP,
    )
    cmdgiteasync.add_argument(
        "--pr-number",
        required=False,
        type=int,
        default=None,
        help="Only consider the specified PR (for manual debugging)",
    )
    cmdgiteasync.set_defaults(func=do_sync_gitea)

    cmdappr = commands.add_parser("inc-approve", help="Approve incidents which passed tests")
    cmdappr.add_argument(
        "--all-incidents",
        action="store_true",
        help="use all incidents without care about rrid",
    )
    cmdappr.add_argument(
        "-I",
        "--incident",
        required=False,
        type=str,
        help="Incident ID (to approve only a single incident)",
    )

    cmdappr.set_defaults(func=do_approve)

    cmdcomment = commands.add_parser("inc-comment", help="Comment incidents in BuildService")
    cmdcomment.set_defaults(func=do_comment)

    cmdincsync = commands.add_parser("inc-sync-results", help="Sync results of openQA incidents jobs to Dashboard")
    cmdincsync.set_defaults(func=do_sync_inc_results)

    cmdaggrsync = commands.add_parser("aggr-sync-results", help="Sync results of openQA aggregates jobs to Dashboard")
    cmdaggrsync.set_defaults(func=do_sync_aggregate_results)

    cmdincrementapprove = commands.add_parser(
        "increment-approve",
        help="Approve the most recent product increment for an OBS project if tests passed",
    )
    cmdincrementapprove.add_argument(
        "--project-base",
        required=False,
        type=str,
        default="SUSE:SLFO:Products:SLES:16.0",
        help="The base for projects on OBS",
    )
    cmdincrementapprove.add_argument(
        "--build-project-suffix",
        required=False,
        type=str,
        default="TEST",
        help="The project on OBS to monitor, schedule jobs for (if --schedule is specified) and approve (if all tests passd)",
    )
    cmdincrementapprove.add_argument(
        "--diff-project-suffix",
        required=False,
        type=str,
        default="PUBLISH/product",
        help="The project on OBS to compute a package diff to",
    )
    cmdincrementapprove.add_argument(
        "--distri",
        required=False,
        type=str,
        default="sle",
        help="Monitor and schedule only products with the specified DISTRI parameter",
    )
    cmdincrementapprove.add_argument(
        "--version",
        required=False,
        type=str,
        default="any",
        help="Monitor and schedule only products with the specified VERSION parameter",
    )
    cmdincrementapprove.add_argument(
        "--flavor",
        required=False,
        type=str,
        default="any",
        help="Monitor and schedule only products with the specified FLAVOR parameter",
    )
    cmdincrementapprove.add_argument(
        "--schedule",
        action="store_true",
        help="Schedule a new product (if none exists or if the most recent product has no jobs)",
    )
    cmdincrementapprove.add_argument(
        "--reschedule",
        action="store_true",
        help="Always schedule a new product (even if one already exists)",
    )
    cmdincrementapprove.add_argument(
        "--accepted",
        action="store_true",
        help="Consider accepted product increment requests as well",
    )
    cmdincrementapprove.add_argument(
        "--request-id",
        required=False,
        type=int,
        help="Check/approve the specified request (instead of the most recent one)",
    )
    cmdincrementapprove.add_argument(
        "--build-listing-sub-path",
        required=False,
        type=str,
        default="product",
        help="The sub path of the file listing used to determine BUILD and other parameters",
    )
    cmdincrementapprove.add_argument(
        "--build-regex",
        required=False,
        type=str,
        default=BUILD_REGEX,
        help="The regex used to determine BUILD and other parameters from the file listing",
    )
    cmdincrementapprove.add_argument(
        "--product-regex",
        required=False,
        type=str,
        default="^SLE.*",
        help="The regex used to determine what products are relevant",
    )
    cmdincrementapprove.add_argument(
        "--increment-config",
        required=False,
        type=Path,
        default=None,
        help="Use configuration from the specified YAML document instead of arguments",
    )
    cmdincrementapprove.set_defaults(func=do_increment_approve, no_config=True)

    repodiff = commands.add_parser(
        "repo-diff",
        help="Computes the diff between two repositories",
    )
    repodiff.add_argument(
        "--repo-a",
        required=False,
        type=str,
        default="SUSE:SLFO:Products:SLES:16.0:TEST/product",
        help="The first repository",
    )
    repodiff.add_argument(
        "--repo-b",
        required=False,
        type=str,
        default="SUSE:SLFO:Products:SLES:16.0:PUBLISH/product",
        help="The second repository",
    )
    repodiff.set_defaults(func=do_repo_diff_computation, no_config=True)

    cmdamqp = commands.add_parser("amqp", help="AMQP listener daemon")
    cmdamqp.add_argument("--url", type=str, default=AMQP_URL, help="the URL of the AMQP server")
    cmdamqp.add_argument(
        "--queue",
        type=str,
        nargs="+",
        default=["openqa", "gitea"],
        help="Specify the queues to listen to. 'openqa' maps to all 'suse.openqa', while 'gitea' maps to the events from PR on Gitea.specify queue to listen to. openqa maps to all suse.openqa, while gitea maps is about the events from PR in gitea.",
    )
    cmdamqp.set_defaults(func=do_amqp)

    return parser
