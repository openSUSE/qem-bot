# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

import requests

from . import QEM_DASHBOARD
from .utils import retry5 as retried_requests


def get_json(route: str, **kwargs: dict) -> str:
    return retried_requests.get(QEM_DASHBOARD + route, **kwargs).json()


def patch(route: str, **kwargs: dict) -> str:
    # openqabot/loader/qem.py originally used req.patch so we will just use that here without retry. Can potentially be changed to used retry5 as requests as
    # well
    return requests.patch(QEM_DASHBOARD + route, timeout=10, **kwargs)


def put(route: str, **kwargs: dict) -> str:
    return retried_requests.put(QEM_DASHBOARD + route, **kwargs)
