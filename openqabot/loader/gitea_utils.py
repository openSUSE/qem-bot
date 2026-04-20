# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Gitea loader utilities."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from io import BytesIO
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lxml import etree  # ty: ignore[unresolved-import]

from openqabot import config
from openqabot.utils import retry10 as retried_requests

if TYPE_CHECKING:
    from collections.abc import Iterator

log = getLogger("bot.loader.gitea_utils")

JsonType = dict[str, Any] | list[Any]


ARCHS = {"x86_64", "aarch64", "ppc64le", "s390x"}


PROJECT_PRODUCT_REGEX = re.compile(r".*:PullRequest:\d+:(.*)")
SCMSYNC_REGEX = re.compile(r".*/products/(.*)#([\d\.]{2,6})$")
VERSION_EXTRACT_REGEX = re.compile(r"[.\d]+")
OBS_PROJECT_SHOW_REGEX = re.compile(r".*/project/show/([^/\s\?\#\)]+)")
# Regex to find all HTTPS URLs, excluding common trailing punctuation like dots or parentheses
# that are likely part of the surrounding text (e.g. at the end of a sentence or in Markdown).
URL_FINDALL_REGEX = re.compile(r"https?://[^\s\?\#\)]*[^\s\?\#\)\.]")


def get_product_name(obs_project: str) -> str:
    """Extract product name from an OBS project name."""
    product_match = PROJECT_PRODUCT_REGEX.search(obs_project)
    return product_match.group(1) if product_match else ""


def get_product_name_and_version_from_scmsync(scmsync_url: str) -> tuple[str, str]:
    """Extract product name and version from an scmsync URL."""
    m = SCMSYNC_REGEX.search(scmsync_url)
    return (m.group(1), m.group(2)) if m else ("", "")


def _extract_version(name: str, prefix: str) -> str:
    """Extract version number from a package name string."""
    remainder = name.removeprefix(prefix)
    return next((part for part in remainder.split("-") if VERSION_EXTRACT_REGEX.search(part)), "")


def _approval_identifiers(bot_user: str, commit_id: str, *, approve: bool = True) -> tuple[str, str]:
    action = "approved" if approve else "decline"
    return f"@{bot_user}: {action}", f"Tested commit: {commit_id}"


def _is_bot_approval_comment(comment: dict[str, Any], bot_user: str, commit_id: str) -> bool:
    """Check if a comment is an authentic approval from the bot."""
    body = comment.get("body", "")
    allowed_authors = {bot_user, config.settings.obs_group}
    is_author = comment.get("user", {}).get("login") in allowed_authors
    review_cmd, commit_str = _approval_identifiers(bot_user, commit_id)
    return is_author and review_cmd in body and commit_str in body


def make_token_header(token: str) -> dict[str, str]:
    """Create the Authorization header for Gitea API requests."""
    return {} if token is None else {"Authorization": "token " + token}


def get_json(
    query: str,
    token: dict[str, str],
    host: str | None = None,
    params: dict[str, Any] | None = None,
) -> JsonType:
    """Fetch JSON data from Gitea API."""
    host = host or config.settings.gitea_url
    url = f"{host}/api/v1/{query}"
    response = retried_requests.get(url, verify=not config.settings.insecure, headers=token, params=params)
    response.raise_for_status()
    return response.json()


def iter_gitea_items(query: str, token: dict[str, str], host: str | None = None) -> Iterator[Any]:
    """Fetch a list of JSON data from Gitea API with pagination support.

    Yields:
        JSON items from the paginated response.

    """
    host = host or config.settings.gitea_url
    url = f"{host}/api/v1/{query}"

    while url:
        response = retried_requests.get(url, verify=not config.settings.insecure, headers=token)
        response.raise_for_status()
        res = response.json()

        if not isinstance(res, list):
            msg = f"Gitea API returned {type(res).__name__} instead of list for query: {query}"
            raise TypeError(msg)

        yield from res
        url = response.links.get("next", {}).get("url")


def _request_json(method: str, query: str, token: dict[str, str], post_data: JsonType, host: str | None = None) -> None:
    """Send a JSON request to Gitea API."""
    host = host or config.settings.gitea_url
    url = f"{host}/api/v1/{query}"
    res = getattr(retried_requests, method.lower())(
        url, verify=not config.settings.insecure, headers=token, json=post_data
    )
    if not res.ok:
        log.error("Gitea API error: %s to %s failed: %s", method.upper(), url, res.text)


def post_json(query: str, token: dict[str, str], post_data: JsonType, host: str | None = None) -> None:
    """Post JSON data to Gitea API."""
    _request_json("POST", query, token, post_data, host)


def patch_json(query: str, token: dict[str, str], post_data: JsonType, host: str | None = None) -> None:
    """Patch JSON data in Gitea API."""
    _request_json("PATCH", query, token, post_data, host)


@lru_cache(maxsize=128)
def read_utf8(name: str) -> str:
    """Read a UTF-8 encoded response file."""
    return Path(f"tests/fixtures/responses/{name}").read_text(encoding="utf8")


@lru_cache(maxsize=128)
def read_json_file(name: str) -> JsonType:
    """Read a JSON response file."""
    return json.loads(read_utf8(name + ".json"))


def read_json_file_list(name: str) -> list[Any]:
    """Read a list from a JSON response file."""
    res = read_json_file(name)
    if not isinstance(res, list):
        msg = f"JSON response file '{name}' returned {type(res).__name__} instead of list"
        raise TypeError(msg)
    return res


@lru_cache(maxsize=128)
def read_xml(name: str) -> etree.ElementTree:
    """Read an XML response file."""
    return etree.parse(BytesIO(read_utf8(name + ".xml").encode("utf-8")))


def reviews_url(repo_name: str, number: int) -> str:
    """Construct the URL for PR reviews."""
    return f"repos/{repo_name}/pulls/{number}/reviews"


def changed_files_url(repo_name: str, number: int) -> str:
    """Construct the URL for PR changed files."""
    return f"repos/{repo_name}/pulls/{number}/files"


def comments_url(repo_name: str, number: int) -> str:
    """Construct the URL for PR comments."""
    return f"repos/{repo_name}/issues/{number}/comments"
