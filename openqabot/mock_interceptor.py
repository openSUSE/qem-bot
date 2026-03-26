# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Mock interceptor for fake_data testing."""

import importlib.util
import json
import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

import requests
import responses

HAS_OSC = importlib.util.find_spec("osc") is not None

log = logging.getLogger("bot.mock_interceptor")


class MockInterceptorState:
    """State container for mock interceptor."""

    started: bool = False
    osc_patcher: Any = None
    osc_conf_patcher: Any = None


def mock_gitea_pulls() -> None:
    """Mock Gitea PRs API."""
    responses.add_callback(
        responses.GET,
        re.compile(r".*/api/v1/repos/.*/pulls(\?state=open.*)?$"),
        callback=gitea_pulls_callback,
    )


def mock_gitea_pr_details() -> None:
    """Mock Gitea PR Details API."""
    responses.add_callback(
        responses.GET,
        re.compile(r".*/api/v1/repos/.*/(?:pulls|issues)/\d+/(?:reviews|comments|files)"),
        callback=gitea_pr_details_callback,
    )


def mock_smelt_graphql() -> None:
    """Mock SMELT GraphQL API."""
    responses.add_callback(
        responses.GET,
        re.compile(r".*/graphql.*"),
        callback=smelt_graphql_callback,
    )


def mock_openqa_jobs() -> None:
    """Mock openQA jobs API."""
    responses.add_callback(
        responses.GET,
        re.compile(r".*/api/v1/jobs.*"),
        callback=openqa_jobs_callback,
    )
    responses.add(
        responses.GET,
        re.compile(r".*/api/v1/job_groups/\d+"),
        json=[{"id": 1, "parent_id": 100}],
    )


def mock_repomd() -> None:
    """Mock repomd.xml API."""
    responses.add(
        responses.GET,
        re.compile(r".*repomd\.xml$"),
        body='<?xml version="1.0" encoding="UTF-8"?><repomd xmlns="http://linux.duke.edu/metadata/repo"><revision>42</revision></repomd>',
        content_type="text/xml",
    )


def mock_patchinfo() -> None:
    """Mock openSUSE OBS patchinfo API."""
    responses.add_callback(
        responses.GET,
        re.compile(r".*_patchinfo$"),
        callback=patchinfo_callback,
    )


def allow_localhost_passthrough() -> None:
    """Allow passthrough to localhost dashboard."""
    responses.add_passthru(re.compile(r"http://localhost:\d+/.*"))


def mock_obs_osc() -> None:
    """Mock OBS osc API connections."""
    if HAS_OSC:
        patcher = patch("osc.connection.http_GET", side_effect=mock_http_get)
        MockInterceptorState.osc_patcher = patcher
        start_func = getattr(patcher, "start", None)
        if callable(start_func):
            start_func()

        conf_patcher = patch("osc.conf.get_config")
        MockInterceptorState.osc_conf_patcher = conf_patcher
        conf_start_func = getattr(conf_patcher, "start", None)
        if callable(conf_start_func):
            conf_start_func()


def setup_mock_responses() -> None:
    """Globally activate mock responses for --fake-data mode."""
    if MockInterceptorState.started:
        return

    log.info("Activating mock responses for --fake-data mode")

    responses.start()
    MockInterceptorState.started = True

    mock_gitea_pulls()
    mock_gitea_pr_details()
    mock_smelt_graphql()
    mock_openqa_jobs()
    mock_repomd()
    mock_patchinfo()
    allow_localhost_passthrough()
    mock_obs_osc()


def read_fixture(name: str) -> str:
    """Read a local fixture file from disk."""
    path = Path(f"tests/fixtures/responses/{name}")
    if path.exists():
        return path.read_text(encoding="utf8")
    return ""


def gitea_pulls_callback(request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
    """Return Gitea PR list mock response."""
    url = str(request.url)
    if "page=1" in url or "page=" not in url:
        return (200, {}, read_fixture("pulls.json"))
    return (200, {}, "[]")


def gitea_pr_details_callback(request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
    """Return Gitea PR details mock response."""
    url = str(request.url)
    if "reviews" in url:
        return (200, {}, read_fixture("reviews-124.json"))
    if "comments" in url:
        return (200, {}, read_fixture("comments-124.json"))
    if "files" in url:
        return (200, {}, read_fixture("files-124.json"))
    return (404, {}, "{}")


def smelt_graphql_callback(_request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
    """Return SMELT GraphQL API mock response."""
    return (
        200,
        {},
        json.dumps({
            "data": {
                "incidents": {
                    "edges": [
                        {
                            "node": {
                                "incidentId": 100,
                                "emu": False,
                                "project": "SUSE:Maintenance:100",
                                "repositories": {"edges": [{"node": {"name": "SUSE:Updates:Mock:15-SP3"}}]},
                                "requestSet": {
                                    "edges": [
                                        {
                                            "node": {
                                                "requestId": 1000,
                                                "status": {"name": "review"},
                                                "reviewSet": {
                                                    "edges": [
                                                        {
                                                            "node": {
                                                                "assignedByGroup": {"name": "qam-openqa"},
                                                                "status": {"name": "new"},
                                                            },
                                                        },
                                                    ],
                                                },
                                            },
                                        },
                                    ],
                                },
                                "packages": {"edges": [{"node": {"name": "mock-package"}}]},
                                "crd": None,
                                "priority": 50,
                            },
                        },
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": ""},
                }
            }
        }),
    )


def openqa_jobs_callback(_request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
    """Return openQA jobs mock response."""
    return (
        200,
        {},
        json.dumps({
            "jobs": [
                {
                    "id": 2,
                    "status": "passed",
                    "result": "passed",
                    "name": "mock_job_git",
                    "group": "Mock Group",
                    "group_id": 1,
                    "clone_id": None,
                    "settings": {
                        "BUILD": ":git:124:tree",
                        "FLAVOR": "Mock-Flavor",
                        "REPOHASH": "42",
                        "VERSION": "15.99",
                    },
                }
            ]
        }),
    )


def patchinfo_callback(_request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
    """Return OBS patchinfo mock response."""
    return (200, {}, read_fixture("patch-info.xml"))


def mock_http_get(url: str, *_args: object, **_kwargs: object) -> BytesIO:
    """Return osc connection mock response."""
    if "_result" in url:
        project = url.split("/build/")[1].split("/", maxsplit=1)[0]
        content = read_fixture(f"build-results-124-{project}.xml")
        if not content:
            content = read_fixture("empty-build-results.xml")
        return BytesIO(content.encode("utf-8"))

    return BytesIO(b"")
