# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Dashboard API client."""

import json
from logging import getLogger
from typing import Any

from .config import settings
from .utils import retry5 as retried_requests

_GET_CACHE: dict[str, Any] = {}
log = getLogger("bot.dashboard")


class MockResponse:
    """Mock requests.Response for dry-runs."""

    def __init__(self, status_code: int, data: dict) -> None:
        """Initialize MockResponse."""
        self.status_code = status_code
        self._data = data

    def json(self) -> dict:
        """Return JSON data."""
        return self._data

    @property
    def text(self) -> str:
        """Return JSON text representation."""
        return json.dumps(self._data)


def clear_cache() -> None:
    """Clear the local cache for dashboard GET requests."""
    _GET_CACHE.clear()


def get_json(route: str, **kwargs: Any) -> Any:  # noqa: ANN401
    """Fetch JSON data from the dashboard with caching."""
    # Use simple key based on route and stringified kwargs
    cache_key = route + str(sorted(kwargs.items()))
    if cache_key in _GET_CACHE:
        return _GET_CACHE[cache_key]

    data = retried_requests.get(settings.dashboard_url(route), **kwargs).json()
    _GET_CACHE[cache_key] = data
    return data


def patch(route: str, **kwargs: Any) -> Any:  # noqa: ANN401
    """Perform a PATCH request to the dashboard."""
    if settings.dry:
        log.info("Dry run: PATCH %s with data: %s", route, kwargs.get("json"))
        return MockResponse(200, {"id": "dry_run"})
    return retried_requests.patch(settings.dashboard_url(route), **kwargs)


def put(route: str, **kwargs: Any) -> Any:  # noqa: ANN401
    """Perform a PUT request to the dashboard."""
    if settings.dry:
        log.info("Dry run: PUT %s with data: %s", route, kwargs.get("json"))
        return MockResponse(200, {"id": "dry_run"})
    return retried_requests.put(settings.dashboard_url(route), **kwargs)
