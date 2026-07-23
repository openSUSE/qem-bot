# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Entry point for the application."""

import hashlib
import sys
import time
import traceback
from collections import defaultdict
from logging import Logger

from dotenv import load_dotenv

import openqabot.config as config_module

from .args import app
from .utils import create_logger

errorcnt = defaultdict(int)
error_limit = 10


def _handle_exception(e: Exception, log: Logger) -> None:
    tb = traceback.extract_tb(e.__traceback__)
    frames = [(frame.filename, frame.name) for frame in tb]
    signature = f"{type(e).__name__}:" + "->".join(f"{filename}:{func_name}" for filename, func_name in frames)
    k = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    errorcnt[k] += 1
    count = errorcnt[k]
    log.debug("exception: %s, errorcount: %d", k, count)
    if count > error_limit:
        log.error("error limit hit for exception %s, reraising", k)
        raise e
    log.info("Exception %s encountered, error count increased", e)


def _run_attempt(attempt: int, log: Logger) -> bool:
    try:
        app()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
        sys.exit(1)
    except Exception as ex:  # noqa: BLE001
        _handle_exception(ex, log)
    else:
        return True

    retries = config_module.settings.app_max_retries
    delay = config_module.settings.app_backoff_factor * attempt
    log.warning("attempt %d/%d failed, retrying in %ds", attempt, retries, delay)
    time.sleep(delay)
    return False


def main() -> None:
    """Run the main entry point of the bot."""
    load_dotenv()
    log = create_logger("bot")
    attempt = 0
    while attempt < config_module.settings.app_max_retries:
        if _run_attempt(attempt, log):
            break
        attempt += 1
