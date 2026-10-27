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
# exit code Typer produces for a SIGINT, e.g. from 'timeout --signal=SIGINT 29m'
SIGINT_EXIT_CODE = 130


def _handle_exception(e: Exception, log: Logger) -> None:
    tb = traceback.extract_tb(e.__traceback__)
    frames = [(frame.filename, frame.name) for frame in tb]
    signature = f"{type(e).__name__}:" + "->".join(f"{filename}:{func_name}" for filename, func_name in frames)
    k = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    errorcnt[k] += 1
    count = errorcnt[k]
    limit = config_module.settings.app_same_error_limit
    log.error("%s(%s) [hash=%s, count=%d]", type(e).__name__, e, k, count, exc_info=e)
    if count > limit:
        log.error("error limit %s hit for exception hash %s, reraising", limit, k)
        raise e


def _run_attempt(attempt: int, log: Logger) -> bool:
    try:
        app()
    except SystemExit as ex:
        # Typer turns a SIGINT into Exit(130), which would leave the CI log without
        # any explanation of the interrupted run
        if ex.code == SIGINT_EXIT_CODE:
            log.info("Interrupted by SIGINT before completing the command")
            raise SystemExit(1) from ex
        raise
    except KeyboardInterrupt:
        log.info("Interrupted by user")
        sys.exit(1)
    except Exception as ex:  # noqa: BLE001
        _handle_exception(ex, log)
    else:
        return True

    retries = config_module.settings.app_max_retries
    if attempt + 1 < retries:
        delay = config_module.settings.app_backoff_factor * attempt
        log.warning("attempt %d/%d failed, retrying in %ds", attempt + 1, retries, delay)
        time.sleep(delay)
    return False


def main() -> None:
    """Run the main entry point of the bot."""
    load_dotenv()
    log = create_logger("bot")
    retries = config_module.settings.app_max_retries
    for attempt in range(retries):
        if _run_attempt(attempt, log):
            return
    log.error("giving up after %s attempt(s), see the reported exception(s) above", retries)
    sys.exit(1)
