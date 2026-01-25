# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest
from pytest_mock import MockerFixture

import responses
from openqabot.config import BUILD_REGEX
from openqabot.incrementapprover import BuildInfo
from openqabot.loader.incrementconfig import IncrementConfig
from openqabot.repodiff import Package
from responses import GET

from .helpers import (
    obs_product_table_url,
    openqa_url,
    prepare_approver,
)


@responses.activate
def test_no_approval_if_no_builds_found(caplog: pytest.LogCaptureFixture) -> None:
    responses.add(GET, obs_product_table_url, json={"data": []})
    approver = prepare_approver(caplog)
    approver()
    assert "Not approving OBS request ID '42' for the following reasons:" in caplog.text
    assert "No builds found for config" in caplog.text


@responses.activate
def test_no_approval_if_one_of_two_configs_has_no_builds(caplog: pytest.LogCaptureFixture) -> None:
    responses.add(GET, obs_product_table_url, json={"data": [{"name": "SLES-16.0-Online-x86_64-Build139.1.spdx.json"}]})
    responses.add(GET, openqa_url, json={"done": {"passed": {"job_ids": [100]}}})

    approver = prepare_approver(caplog)
    config2 = IncrementConfig(
        distri="sle",
        version="16.0",
        flavor="Full-Increments",
        project_base="OBS:PROJECT",
        build_project_suffix="TEST",
        build_listing_sub_path="product",
        build_regex=approver.config[0].build_regex,
        product_regex=".*",
    )
    approver.config.append(config2)
    approver()

    approval_messages = [m for m in caplog.messages if "Approving OBS request ID '42'" in m]
    assert not approval_messages
    assert "Not approving OBS request ID '42' for the following reasons:" in caplog.text
    assert "No builds found for config sle (no settings) in OBS:PROJECT:TEST" in caplog.text
    assert "All 1 openQA jobs have passed/softfailed" not in caplog.text


def testdetermine_build_info_no_match(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(
        distri="other",
        version="any",
        flavor="any",
        project_base="BASE",
        build_project_suffix="TEST",
        product_regex="NOMATCH",
        build_regex=BUILD_REGEX,
    )
    mocker.patch("openqabot.incrementapprover.retried_requests.get").return_value.json.return_value = {
        "data": [{"name": "SLES-16.0-x86_64-Build1.1-Source.report.spdx.json"}]
    }
    res = approver.determine_build_info(config)
    assert res == set()
    config.product_regex = "SLES"
    mocker.patch("openqabot.incrementapprover.retried_requests.get").return_value.json.return_value = {
        "data": [{"name": "SLES-brokenversion-Online-x86_64-Build1.1-Source.report.spdx.json"}]
    }
    res = approver.determine_build_info(config)
    assert res == set()


def test_extra_builds_no_match(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    package = Package("otherpkg", "1", "2", "3", "arch")
    config = IncrementConfig(
        distri="sle",
        version="any",
        flavor="any",
        additional_builds=[{"package_name_regex": "nevermatch", "build_suffix": "suffix"}],
    )
    build_info = BuildInfo("sle", "SLES", "16.0", "flavor", "arch", "1.1")
    res = approver.extra_builds_for_package(package, config, build_info)
    assert res is None


def testdetermine_build_info_missing_flavor_group(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(
        distri="sle",
        version="16.0",
        flavor="any",
        project_base="BASE",
        build_project_suffix="TEST",
        build_regex=r"(?P<product>SLES)-(?P<version>.*)-(?P<arch>.*)-Build(?P<build>.*)-Source.report.spdx.json",
    )
    mocker.patch("openqabot.incrementapprover.retried_requests.get").return_value.json.return_value = {
        "data": [{"name": "SLES-16.0-x86_64-Build1.1-Source.report.spdx.json"}]
    }
    res = approver.determine_build_info(config)
    assert len(res) == 1
    assert next(iter(res)).flavor == "Online-Increments"


def testdetermine_build_info_filter_no_match(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(
        distri="sle",
        version="99.9",
        flavor="any",
        project_base="BASE",
        build_project_suffix="TEST",
        build_regex=BUILD_REGEX,
    )
    mocker.patch("openqabot.incrementapprover.retried_requests.get").return_value.json.return_value = {
        "data": [{"name": "SLES-16.0-Online-x86_64-Build1.1.spdx.json"}]
    }
    res = approver.determine_build_info(config)
    assert res == set()


def test_extra_builds_package_version_regex_no_match(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    package = Package("foo", "1", "2", "3", "arch")
    config = IncrementConfig(
        distri="sle",
        version="any",
        flavor="any",
        additional_builds=[{"package_name_regex": "foo", "package_version_regex": "999", "build_suffix": "suffix"}],
    )
    build_info = BuildInfo("sle", "SLES", "16.0", "flavor", "arch", "1.1")
    res = approver.extra_builds_for_package(package, config, build_info)
    assert res is None
