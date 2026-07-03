# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test increment approver diff."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openqabot.config import settings
from openqabot.loader.incrementconfig import IncrementConfig
from openqabot.types.increment import BuildInfo

from .helpers import prepare_approver

if TYPE_CHECKING:
    import pytest
    from pytest_mock import MockerFixture


def test_package_diff_repo(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(distri="sle", version="any", flavor="any", project_base="BASE", diff_project_suffix="DIFF")
    mock_diff = mocker.patch("openqabot.incrementapprover.RepoDiff")
    mock_diff.return_value.compute_diff.return_value = [{"some": "diff"}, 1]
    res = approver.get_package_diff_from_repo(config, "/product")
    assert res == {"some": "diff"}


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
    diff_key = f"{settings.obs_download_url}/BASE:/TEST/product:{settings.obs_download_url}/BASE:/DIFF"
    approver.package_diff[diff_key] = {"cached": "diff"}
    res = approver.get_package_diff_from_repo(config, "/product")
    assert res == {"cached": "diff"}


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
        reference_repos={"SLES-Increments": "https://ref.repo/SLES"},
    )
    mock_diff = mocker.patch("openqabot.incrementapprover.RepoDiff")
    mock_diff.return_value.compute_diff.return_value = [{"x86_64": {"pkg"}, "noarch": {"npkg"}}, 2]

    # flavor SLES-Increments should use REF_REPO_SLES with augmentation
    build_info_sles = BuildInfo("sle", "SLES", "16.0", "SLES-Increments", "x86_64", "123")
    res = approver.get_package_diff_from_repo(config, "/product", build_info_sles)
    # Expected augmented paths for build_project and diff_project
    mock_diff.return_value.compute_diff.assert_called_with(
        "https://ref.repo/SLES/16.0/DIFF/x86_64",
        f"{settings.obs_download_url}/BASE:/BUILD/product/SLES/x86_64",
    )
    assert res == {"x86_64": {"pkg"}, "noarch": {"npkg"}}

    # flavor SLES-Increments with templates
    config.build_repo_template = "{project}/repo/{product}-{version}-{arch}"
    config.diff_repo_template = "{base}/{version}/{arch}/{suffix}"
    approver.get_package_diff_from_repo(config, "/product", build_info_sles)
    mock_diff.return_value.compute_diff.assert_called_with(
        "https://ref.repo/SLES/16.0/x86_64/DIFF",
        f"{settings.obs_download_url}/BASE:/BUILD/repo/SLES-16.0-x86_64",
    )

    # flavor OTHER should use default DIFF_PROJECT without augmentation (because not in reference_repos)
    config.reference_repos = {"SLES-Increments": "https://ref.repo/SLES"}
    mock_diff.return_value.compute_diff.reset_mock()
    build_info_other = BuildInfo("sle", "SLES", "16.0", "OTHER", "x86_64", "123")
    approver.get_package_diff_from_repo(config, "/product", build_info_other)
    mock_diff.return_value.compute_diff.assert_called_with(
        f"{settings.obs_download_url}/BASE:/DIFF", f"{settings.obs_download_url}/BASE:/BUILD/product"
    )

    # checking via product instead of flavor
    approver.package_diff.clear()
    config.reference_repos = {"SLES": "https://ref.repo/SLES"}
    res = approver.get_package_diff_from_repo(config, "/product", build_info_sles)
    mock_diff.return_value.compute_diff.assert_called_with(
        "https://ref.repo/SLES/16.0/x86_64/DIFF",
        f"{settings.obs_download_url}/BASE:/BUILD/repo/SLES-16.0-x86_64",
    )


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
    res = approver.get_package_diff_from_repo(config, "/product")
    assert res == {}
    assert f"Skipping repo diffing for {settings.obs_download_url}/BASE:/DIFF-Debug" in caplog.text


def test_package_diff_invalid_template(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(
        distri="sle",
        version="16.0",
        flavor="any",
        project_base="BASE",
        build_project_suffix="BUILD",
        diff_project_suffix="DIFF",
        flavor_suffix="Increments",
        reference_repos={"SLES": "https://ref.repo/SLES"},
        build_repo_template="{invalid_var}",
    )
    build_info = BuildInfo("sle", "SLES", "16.0", "SLES-Increments", "x86_64", "123")
    res = approver.get_package_diff_from_repo(config, "/product", build_info)
    assert res == {}
    assert "Invalid template variable in config for sle" in caplog.text
    assert "KeyError: 'invalid_var'" in caplog.text
    assert "Available: base, project, version, arch, channel, suffix, product" in caplog.text
