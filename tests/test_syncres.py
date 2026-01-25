# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

from argparse import Namespace
from typing import cast
from unittest.mock import patch
from urllib.parse import urlparse

from openqabot.syncres import SyncRes
from openqabot.types.types import Data


def test_clone_dry() -> None:
    result = {"job_id": 1, "status": "done"}
    with (
        patch("openqabot.openqa.OpenQAInterface.__bool__", return_value=True),
        patch("openqabot.syncres.post_job") as post_job_mock,
    ):
        SyncRes(
            Namespace(dry=False, token="0", openqa_instance=urlparse("http://instance.qa"))  # noqa: S106
        ).post_result(result)
        post_job_mock.assert_called()


def test_normalize_data_handles_error_gracefully() -> None:
    syncres = SyncRes(Namespace(dry=False, token="0", openqa_instance=urlparse("http://instance.qa")))  # noqa: S106
    with patch("openqabot.syncres.SyncRes.normalize_data", side_effect=KeyError):
        assert syncres._normalize_data(cast("Data", None), cast("dict", None)) is None  # noqa: SLF001


def test_post_result_aggregate() -> None:
    with patch("openqabot.openqa.OpenQAInterface.__bool__", return_value=True):
        syncres = SyncRes(Namespace(dry=False, token="0", openqa_instance=urlparse("http://instance.qa")))  # noqa: S106
        result = {"job_id": 1, "status": "passed", "update_settings": 123}
        with patch("openqabot.syncres.post_job") as mock_post:
            syncres.post_result(result)
            mock_post.assert_called()
