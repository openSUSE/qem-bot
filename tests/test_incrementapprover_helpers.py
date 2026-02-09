# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test increment approver helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

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


def test_extra_builds_for_package_filtering(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    config = approver.config[0]
    config.additional_builds = [
        {
            "build_suffix": "test-build",
            "package_name_regex": ".*",
            "settings": {"FOO": "BAR"},
        }
    ]
    build_info = BuildInfo("sle", "SLES", "16.0", "flavor", "arch", "1.1")

    # Initial livepatch (version 1)
    pkg1 = Package("kernel-livepatch-6.4.0-150600.10", "0", "1", "1.1", "x86_64")
    assert approver.extra_builds_for_package(pkg1, config, build_info) is None

    # Non-initial livepatch (version > 1)
    pkg2 = Package("kernel-livepatch-6.4.0-150600.10", "0", "20240101", "1.1", "x86_64")
    res = approver.extra_builds_for_package(pkg2, config, build_info)
    assert res is not None
    assert res["BUILD"] == "1.1-test-build"

    # debuginfo package
    pkg3 = Package("kernel-livepatch-debuginfo", "0", "20240101", "1.1", "x86_64")
    assert approver.extra_builds_for_package(pkg3, config, build_info) is None

    # src architecture
    pkg4 = Package("kernel-livepatch", "0", "20240101", "1.1", "src")
    assert approver.extra_builds_for_package(pkg4, config, build_info) is None

    # nosrc architecture
    pkg5 = Package("kernel-livepatch", "0", "20240101", "1.1", "nosrc")
    assert approver.extra_builds_for_package(pkg5, config, build_info) is None
