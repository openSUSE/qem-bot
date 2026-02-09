# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test increment approver diff."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openqabot.loader.incrementconfig import IncrementConfig
from openqabot.types.increment import BuildInfo

from .helpers import prepare_approver

if TYPE_CHECKING:
    import pytest
    from pytest_mock import MockerFixture


def testpackage_diff_repo(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(distri="sle", version="any", flavor="any", project_base="BASE", diff_project_suffix="DIFF")
    mock_diff = mocker.patch("openqabot.incrementapprover.RepoDiff")
    mock_diff.return_value.compute_diff.return_value = [{"some": "diff"}, 1]
    res = approver.get_package_diff(None, config, "/product")
    assert res == {"some": "diff"}


def testpackage_diff_none(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(distri="sle", version="any", flavor="any", diff_project_suffix="none")
    res = approver.get_package_diff(None, config, "/product")
    assert res == {}


def testpackage_diff_cached(caplog: pytest.LogCaptureFixture) -> None:
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
    res = approver.get_package_diff(None, config, "/product")
    assert res == {"cached": "diff"}


def testpackage_diff_source_report_no_request(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(
        distri="sle", version="any", flavor="any", project_base="BASE", diff_project_suffix="source-report"
    )
    res = approver.get_package_diff(None, config, "/product")
    assert res == {}
    assert "Source report diff requested but no request found" in caplog.text


def test_package_diff_reference_repos(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(
        distri="sle",
        version="16.0",
        flavor="any",
        project_base="BASE",
        build_project_suffix="BUILD",
        diff_project_suffix="DIFF",
        flavor_suffix="Increments",
        reference_repos={"SLES-Increments": "REF_REPO_SLES"},
    )
    mock_diff = mocker.patch("openqabot.incrementapprover.RepoDiff")
    mock_diff.return_value.compute_diff.return_value = [{"x86_64": {"pkg"}, "noarch": {"npkg"}}, 2]

    # flavor SLES-Increments should use REF_REPO_SLES with augmentation
    build_info_sles = BuildInfo("sle", "SLES", "16.0", "SLES-Increments", "x86_64", "123")
    res = approver.get_package_diff(None, config, "/product", build_info_sles)
    # Expected augmented paths for build_project and diff_project
    mock_diff.return_value.compute_diff.assert_called_with(
        "REF_REPO_SLES/16.0/DIFF/x86_64", "BASE:BUILD/product/SLES/x86_64"
    )
    assert res == {"x86_64": {"pkg"}, "noarch": {"npkg"}}

    # flavor OTHER should use default DIFF_PROJECT without augmentation (because not in reference_repos)
    mock_diff.return_value.compute_diff.reset_mock()
    build_info_other = BuildInfo("sle", "SLES", "16.0", "OTHER", "x86_64", "123")
    approver.get_package_diff(None, config, "/product", build_info_other)
    mock_diff.return_value.compute_diff.assert_called_with("BASE:DIFF", "BASE:BUILD/product")


def test_package_diff_skip_debug(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(
        distri="sle",
        version="any",
        flavor="any",
        project_base="BASE",
        build_project_suffix="BUILD",
        diff_project_suffix="DIFF-Debug",
    )
    res = approver.get_package_diff(None, config, "/product")
    assert res == {}
    assert "Skipping repo diffing for BASE:DIFF-Debug" in caplog.text
