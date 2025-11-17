# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

from typing import NamedTuple
from unittest.mock import patch
from urllib.parse import urlparse

from openqabot.syncres import SyncRes


class Namespace(NamedTuple):
    dry: bool
    token: str
    openqa_instance: str


def test_clone_dry() -> None:
    result = {"job_id": 1, "status": "done"}
    with patch("openqabot.openqa.openQAInterface.__bool__", return_value=True), patch("openqabot.syncres.post_job") as post_job_mock:
        SyncRes(Namespace(dry=False, token=0, openqa_instance=urlparse("http://instance.qa"))).post_result(result)
        post_job_mock.assert_called()
