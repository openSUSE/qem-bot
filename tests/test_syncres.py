# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test SyncRes."""

import logging
from argparse import Namespace
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import pytest
from pytest_mock import MockerFixture

from openqabot.syncres import MAX_CONSECUTIVE_FAILURES, SyncOutcome, SyncRes

if TYPE_CHECKING:
    from openqabot.types.types import Data


def test_clone_dry() -> None:
    result = {"job_id": 1, "status": "done"}
    with (
        patch("openqabot.openqa.OpenQAInterface.__bool__", return_value=True),
        patch("openqabot.syncres.post_job") as post_job_mock,
    ):
        SyncRes(Namespace(dry=False)).post_result(result)
        post_job_mock.assert_called()


def testnormalize_data_safe_handles_error_gracefully() -> None:
    syncres = SyncRes(Namespace(dry=False))
    with patch("openqabot.syncres.SyncRes.normalize_data", side_effect=KeyError):
        assert syncres.normalize_data_safe(cast("Data", None), cast("dict", None)) is None


def test_post_result_aggregate() -> None:
    result = {"job_id": 1, "status": "passed", "update_settings": 123}
    with patch("openqabot.openqa.OpenQAInterface.__bool__", return_value=True):
        syncres = SyncRes(Namespace(dry=False))
        with patch("openqabot.syncres.post_job") as mock_post:
            syncres.post_result(result)
            mock_post.assert_called()
    syncres.dry = True
    with patch("openqabot.syncres.post_job") as mock_post:
        syncres.post_result(result)
        mock_post.assert_not_called()


def test_post_result_returns_post_job_outcome() -> None:
    result = {"job_id": 1, "status": "passed"}
    with patch("openqabot.openqa.OpenQAInterface.__bool__", return_value=True):
        syncres = SyncRes(Namespace(dry=False))
        with patch("openqabot.syncres.post_job", return_value=True):
            assert syncres.post_result(result) is True
        with patch("openqabot.syncres.post_job", return_value=False):
            assert syncres.post_result(result) is False
        syncres.dry = True
        assert syncres.post_result(result) is True


def test_post_results_all_succeed(mocker: MockerFixture) -> None:
    syncres = SyncRes(Namespace(dry=False))
    post_result = mocker.patch.object(syncres, "post_result", return_value=True)
    assert syncres.post_results([{"job_id": 1}, {"job_id": 2}]) == SyncOutcome(failed=0, attempted=2)
    assert post_result.call_count == 2


def test_post_results_continues_after_isolated_failures(mocker: MockerFixture) -> None:
    syncres = SyncRes(Namespace(dry=False))
    mocker.patch.object(syncres, "post_result", side_effect=[False, True, False, True])
    assert syncres.post_results([{}] * 4) == SyncOutcome(failed=2, attempted=4)


def test_post_results_aborts_after_consecutive_failures(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    syncres = SyncRes(Namespace(dry=False))
    total = MAX_CONSECUTIVE_FAILURES + 10
    post_result = mocker.patch.object(syncres, "post_result", return_value=False)
    outcome = syncres.post_results([{}] * total)
    assert outcome == SyncOutcome(failed=MAX_CONSECUTIVE_FAILURES, attempted=MAX_CONSECUTIVE_FAILURES)
    assert post_result.call_count == MAX_CONSECUTIVE_FAILURES
    assert f"after {MAX_CONSECUTIVE_FAILURES} consecutive dashboard failures" in caplog.text
    assert f"10 of {total} results were not posted" in caplog.text


def test_post_results_success_resets_consecutive_counter(mocker: MockerFixture) -> None:
    syncres = SyncRes(Namespace(dry=False))
    pattern = [False] * (MAX_CONSECUTIVE_FAILURES - 1) + [True] + [False] * (MAX_CONSECUTIVE_FAILURES - 1)
    mocker.patch.object(syncres, "post_result", side_effect=pattern)
    outcome = syncres.post_results([{}] * len(pattern))
    assert outcome == SyncOutcome(failed=len(pattern) - 1, attempted=len(pattern))


def test_filter_jobs_accepts_job_with_group(mocker: MockerFixture) -> None:
    syncres = SyncRes(Namespace(dry=False))
    mocker.patch.object(syncres.client, "is_in_devel_group", return_value=False)

    assert syncres.filter_jobs({"id": 1, "group": "FakeGroup", "group_id": 10, "clone_id": None}) is True


@pytest.mark.parametrize(
    "job",
    [
        {"id": 1, "group": "FakeGroup", "clone_id": None},
        {"id": 1, "group": "FakeGroup", "group_id": None, "clone_id": None},
        {"id": 1, "group": "", "group_id": 10, "clone_id": None},
        {"id": 1, "group_id": 10, "clone_id": None},
    ],
)
def test_filter_jobs_rejects_jobs_without_group(job: dict[str, object], caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.syncres")
    syncres = SyncRes(Namespace(dry=False))

    assert syncres.filter_jobs(job) is False
    assert "no job group" in caplog.text
