# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Dashboard API client."""

from typing import Any

import requests

from .config import settings
from .utils import retry5 as retried_requests

_GET_CACHE: dict[str, Any] = {}


def clear_cache() -> None:
    """Clear the local cache for dashboard GET requests.

    The cache lives for the whole process, which is fine for the short-lived
    CLI commands. Long-running callers such as the AMQP daemon must clear it
    whenever the dashboard data may have changed, e.g. once per handled message,
    otherwise a submission's settings are frozen at first read.
    """
    _GET_CACHE.clear()


def get_json(route: str, **kwargs: Any) -> Any:  # ruff: ignore[any-type]
    """Fetch JSON data from the dashboard with caching."""
    # Use simple key based on route and stringified kwargs
    cache_key = route + str(sorted(kwargs.items()))
    if cache_key in _GET_CACHE:
        return _GET_CACHE[cache_key]

    kwargs.setdefault("timeout", settings.url_timeout)
    data = retried_requests.get(settings.dashboard_url(route), **kwargs).json()
    _GET_CACHE[cache_key] = data
    return data


def patch(route: str, **kwargs: Any) -> requests.Response:  # ruff: ignore[any-type]
    """Perform a PATCH request to the dashboard."""
    kwargs.setdefault("timeout", settings.url_timeout)
    return retried_requests.patch(settings.dashboard_url(route), **kwargs)


def put(route: str, **kwargs: Any) -> requests.Response:  # ruff: ignore[any-type]
    """Perform a PUT request to the dashboard."""
    kwargs.setdefault("timeout", settings.url_timeout)
    return retried_requests.put(settings.dashboard_url(route), **kwargs)
