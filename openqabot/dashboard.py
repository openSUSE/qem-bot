# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from typing import Dict

import requests as req

from . import QEM_DASHBOARD
from .utils import retry5 as requests


def get_json(route: str, **kwargs: Dict) -> str:
    return requests.get(QEM_DASHBOARD + route, **kwargs).json()


def patch(route: str, **kwargs: Dict) -> str:
    # openqabot/loader/qem.py originally used req.patch so we will just use that here without retry. Can potentially be changed to used retry5 as requests as
    # well
    return req.patch(QEM_DASHBOARD + route, **kwargs)


def put(route: str, **kwargs: Dict) -> str:
    return requests.put(QEM_DASHBOARD + route, **kwargs)
