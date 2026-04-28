# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Utility functions."""

from __future__ import annotations

import logging
import os
import re
from copy import deepcopy
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

import ruamel.yaml
from requests import Session
from requests.adapters import HTTPAdapter
from ruamel.yaml import YAML
from urllib3.util.retry import Retry

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from .types.types import Data

    class ConfigWithSettings(Protocol):
        """Protocol for configuration objects with settings attribute."""

        settings: dict[str, Any]


ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
T = TypeVar("T", bound="ConfigWithSettings")


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


log = create_logger("bot.utils")


def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from text for resilient matching."""
    return ANSI_ESCAPE_RE.sub("", text)


def normalize_whitespace(text: str) -> str:
    """Collapse multiple spaces and normalize line endings for resilient comparison."""
    # Collapse multiple spaces into one
    text = re.sub(r" +", " ", text)
    # Strip leading/trailing whitespace from each line and the whole block
    return "\n".join(line.strip() for line in text.splitlines()).strip()


def get_yml_list(path: Path) -> list[Path]:
    """Create a list of YAML filenames from a directory or a single file path."""
    return [f for ext in ("yml", "yaml") for f in path.glob("*." + ext)] if path.is_dir() else [path]


def get_configs_from_path(
    path: Path,
    config_key: str,
    loader_func: Callable[[Any], T],
    *,
    load_defaults: bool = True,
) -> list[T]:
    """Load configurations from a file or directory."""
    configs: list[T] = []
    yaml_reader = YAML(typ="safe")

    for file_path in get_yml_list(path):
        try:
            log.debug("Loading %s's configuration from '%s'", config_key, file_path)
            yaml_data = yaml_reader.load(file_path)
            if not yaml_data:
                continue

            raw_items = yaml_data.get(config_key, [])
            if isinstance(raw_items, dict):
                raw_items = list(raw_items.values())

            items = [loader_func(item) for item in raw_items]

            if load_defaults:
                defaults = yaml_data.get("settings", {})
                for item in items:
                    item.settings = defaults | item.settings
            configs.extend(items)
        except AttributeError:
            log.debug("File '%s' skipped: Not a valid %s's configuration", file_path, config_key)
        except (ruamel.yaml.YAMLError, FileNotFoundError, PermissionError) as e:
            log.info("%s's configuration skipped: Could not load '%s': %s", config_key, file_path, e)

    return configs


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


def get_obs_filter_params(pattern: str) -> dict[str, Any]:
    """Reduce data transfer by evaluating the 'REGEX' parameter at the source via 'jsontable'.

    References:
        * https://github.com/openSUSE/MirrorCache/blob/207d61237c0597f8f4ff9d7ad12c4f9cb5d5cd1f/lib/MirrorCache/Datamodule.pm#L309
        * https://github.com/openSUSE/MirrorCache/issues/349
        * https://github.com/openSUSE/MirrorCache/pull/334

    """
    return {"REGEX": pattern, "jsontable": 1}


def unique_dicts(dicts: list[dict[Any, Any]]) -> list[dict[Any, Any]]:
    """De-duplicate a list of dictionaries while preserving order."""
    seen: set[tuple[tuple[Any, Any], ...]] = set()
    unique = []
    for d in dicts:
        # Convert dict to sorted tuple of items for hashability.
        # This assumes values are hashable (strings, numbers, etc.)
        items = tuple(sorted(d.items()))
        if items not in seen:
            seen.add(items)
            unique.append(d)
    return unique


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


retry3 = make_retry_session(3, 2)
retry5 = make_retry_session(5, 1)
retry10 = make_retry_session(10, 0.1)


CONTACT_PATTERN = re.compile(
    r"^\s*(?:[rR]esponsible(?:\s+(?:[pP]erson|[tT]eam|[mM]aintainer))?|(?:[pP]erson|[tT]eam|[mM]aintainer)):\s+(.*)",
    re.MULTILINE,
)


def extract_contact_from_description(description: str | None) -> str | None:
    """Extract contact information from job group description."""
    if not isinstance(description, str):
        return None
    match = CONTACT_PATTERN.search(description)
    return match.group(1).strip() if match else None
