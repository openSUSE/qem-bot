# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Utility functions."""

from __future__ import annotations

import logging
import os
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

if TYPE_CHECKING:
    from pathlib import Path

    from .types.types import Data


def create_logger(name: str) -> logging.Logger:
    """Create and configure a logger with a stream handler."""
    log = logging.getLogger(name)
    log.setLevel(logging.INFO)
    if log.handlers:
        return log
    handler = logging.StreamHandler()
    formatter = logging.Formatter(fmt="%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    return log


def get_yml_list(path: Path) -> list[Path]:
    """Create a list of YAML filenames from a directory or a single file path."""
    return [f for ext in ("yml", "yaml") for f in path.glob("*." + ext)] if path.is_dir() else [path]


def walk(data: list[Any] | dict[str, Any]) -> list[Any] | dict[str, Any]:
    """Recursively process edges and nodes in GraphQL-like dictionary structures."""
    if isinstance(data, list):
        for i, j in enumerate(data):
            data[i] = walk(j)
    if isinstance(data, dict):
        if len(data) == 1:
            if "edges" in data:
                return walk(data["edges"])
            if "node" in data:
                tmp = deepcopy(data["node"])
                del data["node"]
                data.update(tmp)
        for key in data:
            if isinstance(data[key], (list, dict)):
                data[key] = walk(data[key])
    return data


def normalize_results(result: str) -> str:
    """Normalize openQA job result string to dashboard-compatible status."""
    mapping = {
        "passed": "passed",
        "softfailed": "passed",
        "none": "waiting",
        "timeout_exceeded": "stopped",
        "incomplete": "stopped",
        "obsoleted": "stopped",
        "parallel_failed": "stopped",
        "skipped": "stopped",
        "parallel_restarted": "stopped",
        "user_cancelled": "stopped",
        "user_restarted": "stopped",
        "failed": "failed",
    }
    return mapping.get(result, "failed")


def compare_submission_data(sub: Data, message: dict[str, Any]) -> bool:
    """Compare a Data object with a dashboard message dictionary."""
    return all(
        key not in message or getattr(sub, key.lower()) == message[key]
        for key in ("BUILD", "FLAVOR", "ARCH", "DISTRI", "VERSION")
    )


def merge_dicts(dict1: dict[Any, Any], dict2: dict[Any, Any]) -> dict[Any, Any]:
    """Merge two dictionaries, supporting older Python versions."""
    # return `dict1 | dict2` supporting Python < 3.9 which does not yet support this operator
    copy = dict1.copy()
    copy.update(dict2)
    return copy


def number_of_retries(fallback: int = 3) -> int:
    """Determine the number of retries from environment or fallback."""
    return int(os.environ.get("QEM_BOT_RETRIES", 0 if "PYTEST_VERSION" in os.environ else fallback))


def make_retry_session(retries: int, backoff_factor: float) -> Session:
    """Create a requests session with retry capabilities."""
    adapter = HTTPAdapter(
        max_retries=Retry(
            number_of_retries(retries),
            backoff_factor=backoff_factor,
            status_forcelist=frozenset({403, 413, 429, 503}),
        ),
    )
    http = Session()
    http.mount("https://", adapter)
    http.mount("http://", adapter)

    return http


no_retry = make_retry_session(0, 0)
retry3 = make_retry_session(3, 2)
retry5 = make_retry_session(5, 1)
retry10 = make_retry_session(10, 0.1)
