# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test increment approver build info."""

import pytest
import responses
from pytest_mock import MockerFixture
from responses import GET

from openqabot.config import BUILD_REGEX
from openqabot.loader.buildinfo import load_build_info
from openqabot.loader.incrementconfig import IncrementConfig
from openqabot.repodiff import Package
from openqabot.types.increment import BuildInfo

from .helpers import (
    format_increment_url,
    obs_product_table_url,
    prepare_approver,
)


@responses.activate
def test_no_approval_if_no_builds_found(caplog: pytest.LogCaptureFixture) -> None:
    responses.add(GET, obs_product_table_url, json={"data": []})
    approver = prepare_approver(caplog)
    approver()
    assert "Not approving OBS request https://build.suse.de/request/show/42 for the following reasons:" in caplog.text
    assert "No builds found for config" in caplog.text


@responses.activate
def test_no_approval_if_one_of_two_configs_has_no_builds(
    caplog: pytest.LogCaptureFixture, fake_openqa_url_job_stat: str
) -> None:
    responses.add(GET, obs_product_table_url, json={"data": [{"name": "SLES-16.0-Online-x86_64-Build139.1.spdx.json"}]})
    responses.add(GET, fake_openqa_url_job_stat, json={"done": {"passed": {"job_ids": [100]}}})

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

    approval_messages = [
        m for m in caplog.messages if "Approving OBS request https://build.suse.de/request/show/42" in m
    ]
    assert not approval_messages
    assert "Not approving OBS request https://build.suse.de/request/show/42 for the following reasons:" in caplog.text
    assert "No builds found for config sle (no settings) in OBS:PROJECT:TEST" in caplog.text
    assert "All 1 openQA jobs have passed/softfailed" not in caplog.text


def testload_build_info_no_match(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
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
    mocker.patch("openqabot.loader.buildinfo.retried_requests.get").return_value.json.return_value = {
        "data": [{"name": "SLES-16.0-x86_64-Build1.1-Source.report.spdx.json"}]
    }
    res = load_build_info(config, config.build_regex, approver.get_regex_match)
    assert res == set()
    config.product_regex = "SLES"
    mocker.patch("openqabot.loader.buildinfo.retried_requests.get").return_value.json.return_value = {
        "data": [{"name": "SLES-brokenversion-Online-x86_64-Build1.1-Source.report.spdx.json"}]
    }
    res = load_build_info(config, config.build_regex, approver.get_regex_match)
    # load_build_info no longer filters product_regex/version_regex, so it should return one item now
    assert len(res) == 1
    assert not config.accepts_build_info(next(iter(res)))


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


def testload_build_info_missing_flavor_group(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(
        distri="sle",
        version="16.0",
        flavor="any",
        project_base="BASE",
        build_project_suffix="TEST",
        build_regex=r"(?P<product>SLES)-(?P<version>.*)-(?P<arch>.*)-Build(?P<build>.*)-Source.report.spdx.json",
    )
    mocker.patch("openqabot.loader.buildinfo.retried_requests.get").return_value.json.return_value = {
        "data": [{"name": "SLES-16.0-x86_64-Build1.1-Source.report.spdx.json"}]
    }
    res = load_build_info(config, config.build_regex, approver.get_regex_match)
    assert len(res) == 1
    assert next(iter(res)).flavor == "Online-Increments"


def testload_build_info_filter_no_match(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(
        distri="sle",
        version="99.9",
        flavor="any",
        project_base="BASE",
        build_project_suffix="TEST",
        build_regex=BUILD_REGEX,
    )
    mocker.patch("openqabot.loader.buildinfo.retried_requests.get").return_value.json.return_value = {
        "data": [{"name": "SLES-16.0-Online-x86_64-Build1.1.spdx.json"}]
    }
    res = load_build_info(config, config.build_regex, approver.get_regex_match)
    assert len(res) == 1
    assert next(iter(res)).version == "16.0"


def test_extra_builds_additional_builds_no_match_logs_info(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(
        distri="sle",
        version="any",
        flavor="any",
        additional_builds=[{"package_name_regex": "nevermatch", "build_suffix": "suffix"}],
    )
    build_info = BuildInfo("sle", "SLES", "16.0", "flavor", "arch", "1.1")
    res = approver.extra_builds_for_additional_builds({Package("otherpkg", "1", "2", "3", "arch")}, config, build_info)
    assert res == []
    assert (
        "No additional jobs scheduled: additional build 'suffix' (regex: 'nevermatch')"
        " matched 0 packages in the repo diff" in caplog.text
    )
    assert any(r.levelname == "INFO" and "No additional jobs scheduled" in r.message for r in caplog.records)


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


@responses.activate
def test_scheduling_parameters_with_additional_builds(caplog: pytest.LogCaptureFixture) -> None:
    """Verify that additional_builds keys correctly expand into INCREMENT_REPO."""
    approver = prepare_approver(caplog)
    reference_repos = {
        "SLES": "http://download.suse.de/ibs/Products/SLES/16.0",
        "SLES-SAP": None,
    }
    config = IncrementConfig(
        distri="foo",
        version="16.0",
        project_base="OBS:PROJECT",
        flavor="Test-Increments",
        build_project_suffix="TEST",
        build_listing_sub_path="product",
        build_regex="some.*regex",
        product_regex="^Foo.*",
        archs={"aarch64", "x86_64"},
        reference_repos=reference_repos,
        additional_builds=[
            {
                "build_suffix": "kernel-livepatch",
                "archs": ["x86_64"],
                "regex": "kernel-livepatch-(?P<kernel_version>[^-]+(?:-[^-]+)?)(?:-(?P<kind>default))?$",
                "settings": {
                    "FLAVOR": "Test-Increments",
                },
            }
        ],
    )
    base_params = {
        "DISTRI": "sle",
        "VERSION": "16.0",
        "FLAVOR": "Test-Increments",
        "BUILD": "PI-1.1",
        "PRODUCT": "SLES",
        "SUBMISSION_ID": "increment:42",
        "_OBSOLETE": "1",
        "_ONLY_OBSOLETE_SAME_BUILD": "1",
    }
    klp_params = {
        "ARCH": "x86_64",
        "KERNEL_VERSION": "6.12.0-160000.5",
        "BUILD": "PI-1.1-kernel-livepatch-default-6.12.0-160000.5",
    }

    # x86_64 must schedule both regular build and a livepatch
    increment_repos = {format_increment_url(product, "16.0", "x86_64") for product in reference_repos}
    build_info = BuildInfo("sle", "SLES", "16.0", "Test-Increments", "x86_64", "1.1")
    res = approver.make_scheduling_parameters(config, build_info, 42)
    for item in res:
        assert increment_repos == set(item["INCREMENT_REPO"].split(","))
        del item["INCREMENT_REPO"]
    assert base_params | {"ARCH": "x86_64"} in res
    assert base_params | klp_params in res

    # aarch64 must schedule only the regular build
    increment_repos = {format_increment_url(product, "16.0", "aarch64") for product in reference_repos}
    build_info = BuildInfo("sle", "SLES", "16.0", "Test-Increments", "aarch64", "1.1")
    res = approver.make_scheduling_parameters(config, build_info, 42)
    for item in res:
        assert increment_repos == set(item["INCREMENT_REPO"].split(","))
        del item["INCREMENT_REPO"]
    assert base_params | {"ARCH": "aarch64"} in res
    assert not [x for x in res if "KERNEL_VERSION" in x]
