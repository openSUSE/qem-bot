import logging
import sys

from .args import get_parser
from .openqabot import OpenQABot


def create_logger():
    logger = logging.getLogger("bot")
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(levelname)-2s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def main():
    logger = create_logger()
    parser = get_parser()

    if len(sys.argv) < 1:
        parser.print_help()
        sys.exit(0)

    cfg  = parser.parse_args(sys.argv[1:])

    if not cfg.configs.exists() and not cfg.configs.is_dir():
        print(f"Path {args.configs} isn't valid directory with config files")
        sys.exit(1)

    if not hasattr(cfg, "func"):
        print("Command is requred")
        parser.print_help()
        sys.exit(1)

    if cfg.debug:
        logger.setLevel(logging.DEBUG)

    sys.exit(cfg.func(cfg))
