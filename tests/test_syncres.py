# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test SyncRes."""

from argparse import Namespace
from typing import TYPE_CHECKING, cast
from unittest.mock import patch
from urllib.parse import urlparse

from openqabot.syncres import SyncRes

if TYPE_CHECKING:
    from openqabot.types.types import Data


def test_clone_dry() -> None:
    result = {"job_id": 1, "status": "done"}
    with (
        patch("openqabot.openqa.OpenQAInterface.__bool__", return_value=True),
        patch("openqabot.syncres.post_job") as post_job_mock,
    ):
        SyncRes(Namespace(dry=False, token="0", openqa_instance=urlparse("http://instance.qa"))).post_result(result)
        post_job_mock.assert_called()


def testnormalize_data_safe_handles_error_gracefully() -> None:
    syncres = SyncRes(Namespace(dry=False, token="0", openqa_instance=urlparse("http://instance.qa")))
    with patch("openqabot.syncres.SyncRes.normalize_data", side_effect=KeyError):
        assert syncres.normalize_data_safe(cast("Data", None), cast("dict", None)) is None


def test_post_result_aggregate() -> None:
    with patch("openqabot.openqa.OpenQAInterface.__bool__", return_value=True):
        syncres = SyncRes(Namespace(dry=False, token="0", openqa_instance=urlparse("http://instance.qa")))
        result = {"job_id": 1, "status": "passed", "update_settings": 123}
        with patch("openqabot.syncres.post_job") as mock_post:
            syncres.post_result(result)
            mock_post.assert_called()
