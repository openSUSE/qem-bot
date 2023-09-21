# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import ArgumentParser
from pathlib import Path
from urllib.parse import urlparse


def do_full_schedule(args):
    from .openqabot import OpenQABot

    setattr(args, "disable_incidents", False)
    setattr(args, "disable_aggregates", False)

    bot = OpenQABot(args)
    return bot()


def do_incident_schedule(args):
    from .openqabot import OpenQABot

    setattr(args, "disable_incidents", False)
    setattr(args, "disable_aggregates", True)

    bot = OpenQABot(args)
    return bot()


def do_aggregate_schedule(args):
    from .openqabot import OpenQABot

    setattr(args, "disable_aggregates", False)
    setattr(args, "disable_incidents", True)

    bot = OpenQABot(args)
    return bot()


def do_sync_smelt(args):
    from .smeltsync import SMELTSync

    syncer = SMELTSync(args)
    return syncer()


def do_approve(args):
    from .approver import Approver

    approve = Approver(args)
    return approve()


def do_comment(args):
    from .commenter import Commenter

    comment = Commenter(args)
    return comment()


def do_sync_inc_results(args):
    from .incsyncres import IncResultsSync

    syncer = IncResultsSync(args)
    return syncer()


def do_sync_aggregate_results(args):
    from .aggrsync import AggregateResultsSync

    syncer = AggregateResultsSync(args)
    return syncer()


def get_parser():
    parser = ArgumentParser(
        description="QEM-Dashboard, SMELT and openQA connector", prog="qem-bot"
    )

    parser.add_argument(
        "-c",
        "--configs",
        type=Path,
        default=Path("/etc/openqabot"),
        help="Directory or single file with openqabot configuration metadata",
    )

    parser.add_argument(
        "--dry", action="store_true", help="Dry run, do not post any data"
    )

    parser.add_argument(
        "-d", "--debug", action="store_true", help="Enable debug output"
    )

    parser.add_argument(
        "-t", "--token", required=True, type=str, help="Token for qem dashboard api"
    )

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

    cmdfull = commands.add_parser(
        "full-run", help="Full schedule for Maintenance Incidents in openQA"
    )
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

    cmdupd = commands.add_parser(
        "updates-run", help="updates only schedule for Maintenance Incidents in openQA"
    )
    cmdupd.add_argument(
        "-i",
        "--ignore-onetime",
        action="store_true",
        help="Ignore onetime and schedule those test runs",
    )
    cmdupd.set_defaults(func=do_aggregate_schedule)

    cmdsync = commands.add_parser(
        "smelt-sync", help="Sync data from SMELT into QEM Dashboard"
    )
    cmdsync.set_defaults(func=do_sync_smelt)

    cmdappr = commands.add_parser(
        "inc-approve", help="Approve incidents which passed tests"
    )
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

    cmdcomment = commands.add_parser(
        "inc-comment", help="Comment incidents in BuildService"
    )
    cmdcomment.set_defaults(func=do_comment)

    cmdincsync = commands.add_parser(
        "inc-sync-results", help="Sync results of openQA incidents jobs to Dashboard"
    )
    cmdincsync.set_defaults(func=do_sync_inc_results)

    cmdaggrsync = commands.add_parser(
        "aggr-sync-results", help="Sync results of openQA aggregates jobs to Dashboard"
    )
    cmdaggrsync.set_defaults(func=do_sync_aggregate_results)

    return parser
