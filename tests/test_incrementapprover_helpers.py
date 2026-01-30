# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test increment approver helpers."""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

import responses
from openqabot.errors import PostOpenQAError
from openqabot.incrementapprover import BuildInfo

from .helpers import prepare_approver


@responses.activate
@pytest.mark.usefixtures("fake_product_repo")
def testget_regex_match_invalid_pattern(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    approver.get_regex_match("[", "some string")
    assert "Pattern `[` did not compile successfully" in caplog.text


def test_schedule_jobs_dry(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    approver.args.dry = True
    build_info = BuildInfo("sle", "SLES", "16.0", "flavor", "arch", "1.1")
    params = [{"BUILD": "1.1"}]
    mock_post = mocker.patch.object(approver.client, "post_job")
    res = approver.schedule_openqa_jobs(build_info, params)
    assert res == 0
    mock_post.assert_not_called()


def test_schedule_jobs_fail(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    build_info = BuildInfo("sle", "SLES", "16.0", "flavor", "arch", "1.1")
    params = [{"BUILD": "1.1"}]
    mocker.patch.object(approver.client, "post_job", side_effect=PostOpenQAError)
    res = approver.schedule_openqa_jobs(build_info, params)
    assert res == 1
