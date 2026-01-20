# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# ruff: noqa: SLF001
from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

from openqabot.loader.incrementconfig import IncrementConfig

from .helpers import prepare_approver


def test_package_diff_repo(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(distri="sle", version="any", flavor="any", project_base="BASE", diff_project_suffix="DIFF")
    mock_diff = mocker.patch("openqabot.incrementapprover.RepoDiff")
    mock_diff.return_value.compute_diff.return_value = [{"some": "diff"}, 1]
    res = approver._package_diff(None, config, "/product")
    assert res == {"some": "diff"}


def test_package_diff_none(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(distri="sle", version="any", flavor="any", diff_project_suffix="none")
    res = approver._package_diff(None, config, "/product")
    assert res == {}


def test_package_diff_cached(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(
        distri="sle",
        version="any",
        flavor="any",
        project_base="BASE",
        build_project_suffix="TEST",
        diff_project_suffix="DIFF",
    )
    diff_key = "BASE:TEST/product:BASE:DIFF"
    approver.package_diff[diff_key] = {"cached": "diff"}
    res = approver._package_diff(None, config, "/product")
    assert res == {"cached": "diff"}


def test_package_diff_source_report_no_request(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(
        distri="sle", version="any", flavor="any", project_base="BASE", diff_project_suffix="source-report"
    )
    res = approver._package_diff(None, config, "/product")
    assert res == {}
    assert "Source report diff requested but no request found" in caplog.text
