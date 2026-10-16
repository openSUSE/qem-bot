# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test increment approver diff."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .helpers import prepare_approver

if TYPE_CHECKING:
    import pytest
    from pytest_mock import MockerFixture


def test_package_diff_repo(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    mock_diff = mocker.patch("openqabot.incrementapprover.RepoDiff")
    mock_diff.return_value.compute_diff.return_value = [{"some": "diff"}, 1]
    res = approver.get_package_diff_from_repo("build_url", "ref_url")
    assert res == {"some": "diff"}


def test_package_diff_cached(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    approver.package_diff["build_url:ref_url"] = {"cached": "diff"}
    res = approver.get_package_diff_from_repo("build_url", "ref_url")
    assert res == {"cached": "diff"}
