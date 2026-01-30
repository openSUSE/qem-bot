# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Entry point for the application."""

import logging
import sys

from .args import get_parser
from .utils import create_logger


def main() -> None:
    log = create_logger("bot")
    parser = get_parser()

    if len(sys.argv) < 1:
        parser.print_help()
        sys.exit(0)

    cfg = parser.parse_args(sys.argv[1:])

    if not cfg.configs.is_dir() and not hasattr(cfg, "no_config"):
        log.error("Configuration error: %s is not a valid directory", cfg.configs)
        sys.exit(1)

    if not hasattr(cfg, "func"):
        log.error("Command is required")
        parser.print_help()
        sys.exit(1)

    if cfg.debug:
        log.setLevel(logging.DEBUG)

    try:
        sys.exit(cfg.func(cfg))
    except KeyboardInterrupt:
        log.info("Interrupted by user")
        sys.exit(1)
