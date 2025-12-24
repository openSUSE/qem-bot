# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

from typing import Any

import requests

from .config import QEM_DASHBOARD
from .utils import retry5 as retried_requests


def get_json(route: str, **kwargs: Any) -> Any:
    return retried_requests.get(QEM_DASHBOARD + route, **kwargs).json()


def patch(route: str, **kwargs: Any) -> requests.Response:
    # openqabot/loader/qem.py originally used req.patch so we will just use that here without retry. Can potentially be
    # changed to used retry5 as requests as well
    return requests.patch(QEM_DASHBOARD + route, timeout=10, **kwargs)


def put(route: str, **kwargs: Any) -> requests.Response:
    return retried_requests.put(QEM_DASHBOARD + route, **kwargs)
