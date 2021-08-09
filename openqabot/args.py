from argparse import ArgumentParser
from pathlib import Path


def get_parser():
    parser = ArgumentParser()
    parser.add_argument(
        "-c",
        "--configs",
        type=Path,
        default=Path("/etc/openqabot"),
        help="Directory with openqabot configuration metadata",
    )
    parser.add_argument(
        "--dry", action="store_true", help="Dry run, dont post any data"
    )
    parser.add_argument(
        "--disable-aggregates", action="store_true", help="Don't schedule aggregates"
    )
    parser.add_argument(
        "--disable-incidents", action="store_true", help="Don't schedule incidents"
    )
    parser.add_argument(
        "-i",
        "--ignore-onetime",
        action="store_true",
        help="Ignore onetime and schedule those test runs",
        default=False,
        dest="ignore_onetime",
    )
    parser.add_argument(
        "-d", "--debug", action="store_true", help="Enable debug output"
    )
    parser.add_argument(
        "-t", "--token", required=True, type=str, help="Token for qem dashboard api"
    )
    return parser
