# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Dashboard API client."""

from typing import Any

import requests

from .config import QEM_DASHBOARD
from .utils import retry5 as retried_requests

_GET_CACHE: dict[str, Any] = {}


def clear_cache() -> None:
    _GET_CACHE.clear()


def get_json(route: str, **kwargs: Any) -> Any:  # noqa: ANN401
    # Use simple key based on route and stringified kwargs
    cache_key = route + str(sorted(kwargs.items()))
    if cache_key in _GET_CACHE:
        return _GET_CACHE[cache_key]

    data = retried_requests.get(QEM_DASHBOARD + route, **kwargs).json()
    _GET_CACHE[cache_key] = data
    return data


def patch(route: str, **kwargs: Any) -> requests.Response:  # noqa: ANN401
    # openqabot/loader/qem.py originally used req.patch so we will just use that here without retry. Can potentially be
    # changed to used retry5 as requests as well
    return requests.patch(QEM_DASHBOARD + route, timeout=10, **kwargs)


def put(route: str, **kwargs: Any) -> requests.Response:  # noqa: ANN401
    return retried_requests.put(QEM_DASHBOARD + route, **kwargs)
