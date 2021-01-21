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
    args = get_parser().parse_args(sys.argv[1:])

    if not args.configs.exists() and not args.configs.is_dir():
        print(f"Path {args.configs} isn't valid directory with config files")
        sys.exit(1)

    if args.debug:
        logger.setLevel(logging.DEBUG)

    bot = OpenQABot(args)

    sys.exit(bot())
