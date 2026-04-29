# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test increment approver helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import responses

from openqabot.errors import PostOpenQAError
from openqabot.incrementapprover import BuildInfo
from openqabot.repodiff import Package

from .helpers import prepare_approver

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@responses.activate
@pytest.mark.usefixtures("fake_product_repo")
def testget_regex_match_invalid_pattern(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    approver.get_regex_match("[", "some string")
    assert "Pattern `[` did not compile successfully" in caplog.text


def test_schedule_jobs_dry(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    approver.client.dry = True
    build_info = BuildInfo("sle", "SLES", "16.0", "flavor", "arch", "1.1")
    params = [{"BUILD": "1.1"}]
    mock_post = mocker.patch.object(approver.client.openqa, "openqa_request")
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


@pytest.mark.parametrize(
    ("pkg", "additional_builds", "expected_build"),
    [
        # Initial version exclusion
        (Package("kernel-livepatch", "0", "1", "1.1", "x86_64"), [{"regex": ".*", "build_suffix": "test"}], None),
        # Normal match
        (
            Package("kernel-livepatch", "0", "20240101", "1.1", "x86_64"),
            [{"regex": ".*", "build_suffix": "test"}],
            "PI-1.1-test",
        ),
        # Debug package exclusion
        (
            Package("kernel-livepatch-debuginfo", "0", "20240101", "1.1", "x86_64"),
            [{"regex": ".*", "build_suffix": "test"}],
            None,
        ),
        # src arch exclusion
        (Package("kernel-livepatch", "0", "20240101", "1.1", "src"), [{"regex": ".*", "build_suffix": "test"}], None),
        # nosrc arch exclusion
        (Package("kernel-livepatch", "0", "20240101", "1.1", "nosrc"), [{"regex": ".*", "build_suffix": "test"}], None),
        # Arch filtering - matching
        (
            Package("kernel-livepatch", "0", "20240101", "1.1", "x86_64"),
            [{"regex": ".*", "build_suffix": "test", "archs": ["x86_64"]}],
            "PI-1.1-test",
        ),
        # Arch filtering - mismatch
        (
            Package("kernel-livepatch", "0", "20240101", "1.1", "s390x"),
            [{"regex": ".*", "build_suffix": "test", "archs": ["x86_64"]}],
            None,
        ),
        # Placeholder (empty version)
        (Package("kernel-livepatch", "0", "", "1.1", "x86_64"), [{"regex": ".*", "build_suffix": "test"}], None),
        # With settings already present
        (
            Package("kernel-livepatch", "0", "20240101", "1.1", "x86_64"),
            [{"regex": ".*", "build_suffix": "test", "settings": {"BAR": "BAZ"}}],
            "PI-1.1-test",
        ),
    ],
)
def test_extra_builds_for_package_parametrized(
    caplog: pytest.LogCaptureFixture,
    pkg: Package,
    additional_builds: list[dict[str, Any]],
    expected_build: str | None,
) -> None:
    approver = prepare_approver(caplog)
    config = approver.config[0]
    for b in additional_builds:
        if "settings" not in b:
            b["settings"] = {}
    config.additional_builds = additional_builds
    build_info = BuildInfo("sle", "SLES", "16.0", "flavor", "arch", "1.1")

    res = approver.extra_builds_for_package(pkg, config, build_info)
    if expected_build is None:
        assert res is None
    else:
        assert res is not None
        assert res["BUILD"] == expected_build


def test_filter_results(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    mocker.patch.object(approver.client, "is_in_devel_group", side_effect=lambda j: j.get("group_id") == 9)

    results = [
        {
            "passed": {"j1": {"job_ids": [1], "group_id": 1}, "j2": {"job_ids": [1, 2], "group_id": 9}},
            "failed": {"j3": {"job_ids": [2], "group_id": 9}},
        }
    ]
    expected = [{"passed": {"j1": {"job_ids": [1], "group_id": 1}}}]
    assert approver._filter_results(results) == expected  # noqa: SLF001


@responses.activate
def test_request_openqa_job_results_enrichment_missing_data(
    caplog: pytest.LogCaptureFixture, mocker: MockerFixture
) -> None:
    """Test job results enrichment with missing or incomplete data."""
    approver = prepare_approver(caplog)

    mock_stats = {
        "done": {
            "passed": {"no_job_ids": []},  # Missing job_ids
            "failed": {"job_ids": ["123"]},  # get_single_job will return None
        }
    }

    mocker.patch.object(approver.client, "get_scheduled_product_stats", return_value=mock_stats)
    mocker.patch.object(approver.client, "get_jobs_by_ids", return_value=[])

    params: list[dict[str, str]] = [
        {
            "DISTRI": "sle",
            "VERSION": "15-SP4",
            "FLAVOR": "Online",
            "ARCH": "x86_64",
            "BUILD": "123",
            "PRODUCT": "SLES",
        }
    ]

    res = approver.request_openqa_job_results(params, "info")

    assert len(res) == 1
    assert "done" in res[0]
