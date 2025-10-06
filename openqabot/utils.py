# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import logging
from copy import deepcopy
from typing import Optional, List
from pathlib import Path

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .types import Data


def create_logger(name: str) -> logging.Logger:
    log = logging.getLogger(name)
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    return log


def get_yml_list(path: Path) -> List[Path]:
    """Create a list of YML filenames from a folder or single file path."""
    return (
        [f for ext in ("yml", "yaml") for f in path.glob("*." + ext)]
        if path.is_dir()
        else [path]
    )


def walk(inc):
    if isinstance(inc, list):
        for i, j in enumerate(inc):
            inc[i] = walk(j)
    if isinstance(inc, dict):
        if len(inc) == 1:
            if "edges" in inc:
                return walk(inc["edges"])
            if "node" in inc:
                tmp = deepcopy(inc["node"])
                del inc["node"]
                inc.update(tmp)
        for key in inc:
            if isinstance(inc[key], (list, dict)):
                inc[key] = walk(inc[key])
    return inc


def normalize_results(result: str) -> str:
    if result in ("passed", "softfailed"):
        return "passed"
    if result == "none":
        return "waiting"
    if result in (
        "timeout_exceeded",
        "incomplete",
        "obsoleted",
        "parallel_failed",
        "skipped",
        "parallel_restarted",
        "user_cancelled",
        "user_restarted",
    ):
        return "stopped"
    if result == "failed":
        return "failed"

    return "failed"


def compare_incident_data(inc: Data, message) -> bool:
    for key in ("BUILD", "FLAVOR", "ARCH", "DISTRI", "VERSION"):
        if key in message and getattr(inc, key.lower()) != message[key]:
            return False
    return True


def __retry(retries: Optional[int], backoff_factor: float) -> Session:
    adapter = HTTPAdapter(
        max_retries=Retry(
            retries,
            backoff_factor=backoff_factor,
            status_forcelist=frozenset({403, 413, 429, 503}),
        )
    )
    http = Session()
    http.mount("https://", adapter)
    http.mount("http://", adapter)

    return http


no_retry = __retry(None, 0)
retry3 = __retry(3, 2)
retry5 = __retry(5, 1)
retry10 = __retry(10, 0.1)
