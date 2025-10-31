# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# ruff: noqa: S106 "Possible hardcoded password assigned to argument"

import logging
import os
from collections import namedtuple
from pathlib import Path
from typing import Any, List, Optional, Tuple
from urllib.parse import urlparse

import osc.conf
import osc.core
import pytest
from _pytest.logging import LogCaptureFixture
from pytest import MonkeyPatch

import openqabot
import responses
from openqabot import BUILD_REGEX, OBS_DOWNLOAD_URL, OBS_GROUP, OBS_URL
from openqabot.incrementapprover import IncrementApprover
from openqabot.loader.gitea import read_json
from openqabot.loader.incrementconfig import IncrementConfig
from responses import GET

# Fake Namespace for IncrementApprover initialization
_namespace = namedtuple(
    "Namespace",
    (
        "dry",
        "token",
        "openqa_instance",
        "accepted",
        "request_id",
        "project_base",
        "build_project_suffix",
        "diff_project_suffix",
        "distri",
        "version",
        "flavor",
        "schedule",
        "reschedule",
        "build_listing_sub_path",
        "build_regex",
        "product_regex",
        "fake_data",
        "increment_config",
        "packages",
        "archs",
        "settings",
        "additional_builds",
    ),
)

# define fake data
ReviewState = namedtuple("ReviewState", ("state", "by_group"))
openqa_url = "http://openqa-instance/api/v1/isos/job_stats"


@pytest.fixture(scope="function")
def fake_no_jobs() -> None:
    responses.add(GET, openqa_url, json={})


@pytest.fixture(scope="function")
def fake_pending_jobs() -> None:
    responses.add(GET, openqa_url, json={"scheduled": {}, "running": {}})


@pytest.fixture(scope="function")
def fake_not_ok_jobs() -> None:
    responses.add(
        GET,
        openqa_url,
        json={"done": {"passed": {"job_ids": [20]}, "failed": {"job_ids": [21]}}},
    )


@pytest.fixture(scope="function")
def fake_ok_jobs() -> None:
    responses.add(
        GET,
        openqa_url,
        json={"done": {"passed": {"job_ids": [20]}, "softfailed": {"job_ids": [21]}}},
    )


@pytest.fixture(scope="function")
def fake_product_repo() -> None:
    responses.add(
        GET,
        OBS_DOWNLOAD_URL + "/OBS:/PROJECT:/TEST/product/?jsontable=1",
        json=read_json("test-product-repo"),
    )


def fake_osc_get_config(override_apiurl: str) -> None:
    assert override_apiurl == OBS_URL


def fake_get_request_list(url: str, project: str, **_kwargs: Any) -> List[osc.core.Request]:
    assert url == OBS_URL
    assert project == "OBS:PROJECT:TEST"
    req = osc.core.Request()
    req.reqid = 42
    req.state = "review"
    req.reviews = [ReviewState("review", OBS_GROUP)]
    return [req]


def fake_change_review_state(apiurl: str, reqid: str, newstate: str, by_group: str, message: str) -> None:
    assert apiurl == OBS_URL
    assert reqid == "42"
    assert newstate == "accepted"
    assert by_group == OBS_GROUP
    assert message == "All 2 jobs on openQA have passed/softfailed"


def run_approver(
    caplog: LogCaptureFixture,
    monkeypatch: MonkeyPatch,
    schedule: bool = False,
    diff_project_suffix: str = "none",
    test_env_var: str = "",
    config: Optional[IncrementConfig] = None,
) -> Tuple[int, List]:
    jobs = []
    os.environ["CI_JOB_URL"] = test_env_var
    caplog.set_level(logging.DEBUG, logger="bot.increment_approver")
    monkeypatch.setattr(osc.core, "get_request_list", fake_get_request_list)
    monkeypatch.setattr(osc.core, "change_review_state", fake_change_review_state)
    monkeypatch.setattr(osc.conf, "get_config", fake_osc_get_config)
    monkeypatch.setattr(
        openqabot.openqa.openQAInterface,
        "post_job",
        lambda _self, data: jobs.append(data),
    )
    args = _namespace(
        dry=False,
        token="not-secret",
        openqa_instance=urlparse("http://openqa-instance"),
        accepted=True,
        request_id=None,
        project_base="OBS:PROJECT",
        build_project_suffix="TEST",
        diff_project_suffix=diff_project_suffix,
        distri="sle",
        version="16.0",
        flavor="Online-Increments",
        schedule=schedule,
        reschedule=False,
        build_listing_sub_path="product",
        build_regex=BUILD_REGEX,
        product_regex=".*",
        fake_data=True,
        increment_config=None,
        packages=[] if config is None else config.packages,
        archs=set() if config is None else config.archs,
        settings={} if config is None else config.settings,
        additional_builds=[] if config is None else config.additional_builds,
    )
    increment_approver = IncrementApprover(args)
    errors = increment_approver()
    return (errors, jobs)


@responses.activate
@pytest.mark.usefixtures("fake_no_jobs", "fake_product_repo")
def test_skipping_with_no_openqa_jobs(
    caplog: LogCaptureFixture,
    monkeypatch: MonkeyPatch,
) -> None:
    run_approver(caplog, monkeypatch)
    messages = [x[-1] for x in caplog.record_tuples]
    assert (
        "Skipping approval, there are no relevant jobs on openQA for SLESv16.0 build 139.1@aarch64 of flavor Online-Increments"
        in messages
    )


@responses.activate
@pytest.mark.usefixtures("fake_no_jobs", "fake_product_repo")
def test_scheduling_with_no_openqa_jobs(
    caplog: LogCaptureFixture,
    monkeypatch: MonkeyPatch,
) -> None:
    ci_job_url = "https://some/ci/job/url"
    (errors, jobs) = run_approver(caplog, monkeypatch, schedule=True, test_env_var=ci_job_url)
    messages = [x[-1] for x in caplog.record_tuples]
    assert (
        "Skipping approval, there are no relevant jobs on openQA for SLESv16.0 build 139.1@aarch64 of flavor Online-Increments"
        in messages
    )
    assert errors == 0, "no errors"
    for arch in ["x86_64", "aarch64", "ppc64le", "s390x"]:
        assert {
            "DISTRI": "sle",
            "VERSION": "16.0",
            "FLAVOR": "Online-Increments",
            "BUILD": "139.1",
            "ARCH": arch,
            "INCREMENT_REPO": "http://%REPO_MIRROR_HOST%/ibs/OBS:/PROJECT:/TEST/product",
            "__CI_JOB_URL": ci_job_url,
        } in jobs, f"{arch} jobs created"


@responses.activate
@pytest.mark.usefixtures("fake_no_jobs", "fake_product_repo")
def test_scheduling_extra_livepatching_builds_with_no_openqa_jobs(
    caplog: LogCaptureFixture,
    monkeypatch: MonkeyPatch,
) -> None:
    path = Path("tests/fixtures/config-increment-approver/increment-definitions.yaml")
    config = next(IncrementConfig.from_config_file(path))
    (errors, jobs) = run_approver(
        caplog,
        monkeypatch,
        schedule=True,
        diff_project_suffix="PUBLISH/product",
        config=config,
    )
    messages = [x[-1] for x in caplog.record_tuples]
    assert (
        "Skipping approval, there are no relevant jobs on openQA for SLESv16.0 build 139.1@aarch64 of flavor Online-Increments"
        in messages
    )
    assert errors == 0, "no errors"
    base_params = {
        "DISTRI": "sle",
        "VERSION": "16.0",
        "FLAVOR": "Online-Increments",
        "BUILD": "139.1",
        "INCREMENT_REPO": "http://%REPO_MIRROR_HOST%/ibs/OBS:/PROJECT:/TEST/product",
        "FOO": "bar",
    }
    for arch in ["x86_64", "aarch64", "ppc64le"]:
        assert base_params | {"ARCH": arch} in jobs, f"regular {arch} jobs created"
    assert base_params | {"ARCH": "s390x"} not in jobs, "s390x filtered out"

    expected_livepatch_params = base_params | {
        "FLAVOR": "Default-qcow-Updates",
        "BUILD": "139.1-kernel-livepatch-6.12.0-160000.5",
        "KERNEL_VERSION": "6.12.0-160000.5",
        "KGRAFT": "1",
    }
    expected_livepatch_rt_params = expected_livepatch_params | {
        "FLAVOR": "Base-RT-Updates",
        "BUILD": "139.1-kernel-livepatch-rt-6.12.0-160000.5",
    }
    assert expected_livepatch_params | {"ARCH": "ppc64le"} in jobs, (
        "additional kernel livepatch jobs of default flavor created"
    )
    assert expected_livepatch_rt_params | {"ARCH": "ppc64le"} in jobs, (
        "additional kernel livepatch jobs of RT flavor created"
    )
    assert expected_livepatch_params | {"ARCH": "aarch64"} not in jobs, (
        "additional kernel livepatch jobs only created if package is new"
    )


@responses.activate
@pytest.mark.usefixtures("fake_pending_jobs", "fake_product_repo")
def test_skipping_with_pending_openqa_jobs(caplog: LogCaptureFixture, monkeypatch: MonkeyPatch) -> None:
    run_approver(caplog, monkeypatch)
    messages = [x[-1] for x in caplog.record_tuples]
    assert (
        "Skipping approval, some jobs on openQA for SLESv16.0 build 139.1@aarch64 of flavor Online-Increments are in pending states (running, scheduled)"
        in messages
    )


@responses.activate
@pytest.mark.usefixtures("fake_not_ok_jobs", "fake_product_repo")
def test_listing_not_ok_openqa_jobs(
    caplog: LogCaptureFixture,
    monkeypatch: MonkeyPatch,
) -> None:
    run_approver(caplog, monkeypatch)
    last_message = [x[-1] for x in caplog.record_tuples][-1]
    assert "The following openQA jobs ended up with result 'failed'" in last_message
    assert "http://openqa-instance/tests/21" in last_message
    assert "http://openqa-instance/tests/20" not in last_message


@responses.activate
@pytest.mark.usefixtures("fake_ok_jobs", "fake_product_repo")
def test_approval_if_there_are_only_ok_openqa_jobs(
    caplog: LogCaptureFixture,
    monkeypatch: MonkeyPatch,
) -> None:
    run_approver(caplog, monkeypatch)
    last_message = [x[-1] for x in caplog.record_tuples][-1]
    assert "All 2 jobs on openQA have passed/softfailed" in last_message


def test_config_parsing(caplog: LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.increment_config")
    path = Path("tests/fixtures/config-increment-approver")
    configs = [*IncrementConfig.from_config_path(path)]
    assert configs[0].distri == "foo"
    assert configs[0].version == "any"
    assert configs[0].flavor == "any"
    assert configs[0].project_base == "FOO"
    assert configs[0].build_project_suffix == "TEST"
    assert configs[0].diff_project_suffix == "PUBLISH/product"
    assert configs[0].build_listing_sub_path == "product"
    assert configs[0].build_regex == "some.*regex"
    assert configs[0].product_regex == "^Foo.*"
    assert configs[0].archs == {"x86_64", "aarch64", "ppc64le"}
    assert configs[0].packages == ["kernel-source", "kernel-azure"]
    assert configs[0].build_project() == "FOO:TEST"
    assert configs[0].diff_project() == "FOO:PUBLISH/product"
    assert configs[1].distri == "bar"
    assert configs[1].version == "42"
    assert configs[1].flavor == "Test-Increments"
    assert configs[1].project_base == ""
    assert configs[1].build_project() == "ToTest"
    assert configs[1].diff_project() == "none"

    path = Path("tests/fixtures/config")
    caplog.set_level(logging.DEBUG, logger="bot.increment_approver")
    configs = IncrementConfig.from_config_path(path)
    assert [*configs] == []
    messages = [x[-1][0:52] for x in caplog.record_tuples]
    assert "Unable to load config file 'tests/fixtures/config/01" in messages
    assert "Reading config file 'tests/fixtures/config/03_no_tes" in messages
