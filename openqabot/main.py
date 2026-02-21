# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Entry point for the application."""

import sys

from .args import app
from .utils import create_logger


def main() -> None:
    """Run the main entry point of the bot."""
    log = create_logger("bot")
    try:
        app()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        log.error(e)  # noqa: TRY400
        sys.exit(1)
