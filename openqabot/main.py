# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import logging
import sys

from .args import get_parser


def create_logger() -> logging.Logger:
    logger = logging.getLogger("bot")
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def main() -> None:
    logger = create_logger()
    parser = get_parser()

    if len(sys.argv) < 1:
        parser.print_help()
        sys.exit(0)

    cfg = parser.parse_args(sys.argv[1:])

    if not cfg.configs.exists() and not cfg.configs.is_dir():
        logger.error(f"Path {cfg.configs} is not a valid directory with config files")
        sys.exit(1)

    if not hasattr(cfg, "func"):
        logger.error("Command is required")
        parser.print_help()
        sys.exit(1)

    if cfg.debug:
        logger.setLevel(logging.DEBUG)

    sys.exit(cfg.func(cfg))
