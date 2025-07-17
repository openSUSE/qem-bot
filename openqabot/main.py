# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import logging
import sys

from .utils import create_logger
from .args import get_parser


def main() -> None:
    log = create_logger("bot")
    parser = get_parser()

    if len(sys.argv) < 1:
        parser.print_help()
        sys.exit(0)

    cfg = parser.parse_args(sys.argv[1:])

    if (
        not cfg.configs.exists()
        and not cfg.configs.is_dir()
        and not hasattr(cfg, "no_config")
    ):
        log.error("Path %s is not a valid directory with config files", cfg.configs)
        sys.exit(1)

    if not hasattr(cfg, "func"):
        log.error("Command is required")
        parser.print_help()
        sys.exit(1)

    if cfg.debug:
        log.setLevel(logging.DEBUG)

    sys.exit(cfg.func(cfg))
