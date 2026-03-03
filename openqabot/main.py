# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Entry point for the application."""

import sys

from dotenv import load_dotenv

from .args import app
from .utils import create_logger


def main() -> None:
    """Run the main entry point of the bot."""
    load_dotenv()
    log = create_logger("bot")
    try:
        app()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
        sys.exit(1)
