# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Dashboard API client."""

from typing import Any

import requests

from .config import settings
from .utils import retry5 as retried_requests

_GET_CACHE: dict[str, Any] = {}


def clear_cache() -> None:
    """Clear the local cache for dashboard GET requests."""
    _GET_CACHE.clear()


def get_json(route: str, **kwargs: Any) -> Any:  # noqa: ANN401
    """Fetch JSON data from the dashboard with caching."""
    # Use simple key based on route and stringified kwargs
    cache_key = route + str(sorted(kwargs.items()))
    if cache_key in _GET_CACHE:
        return _GET_CACHE[cache_key]

    data = retried_requests.get(settings.qem_dashboard_url + route, **kwargs).json()
    _GET_CACHE[cache_key] = data
    return data


def patch(route: str, **kwargs: Any) -> requests.Response:  # noqa: ANN401
    """Perform a PATCH request to the dashboard."""
    # openqabot/loader/qem.py originally used req.patch so we will just use that here without retry. Can potentially be
    # changed to used retry5 as requests as well
    return requests.patch(settings.qem_dashboard_url + route, timeout=10, **kwargs)


def put(route: str, **kwargs: Any) -> requests.Response:  # noqa: ANN401
    """Perform a PUT request to the dashboard."""
    return retried_requests.put(settings.qem_dashboard_url + route, **kwargs)
