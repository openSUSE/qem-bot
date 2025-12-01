# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# ruff: noqa: S106 "Possible hardcoded password assigned to argument"
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlparse

import osc.conf
import osc.core
import pytest

import openqabot
import responses
from openqabot.config import BUILD_REGEX, OBS_DOWNLOAD_URL, OBS_GROUP, OBS_URL
from openqabot.incrementapprover import IncrementApprover
from openqabot.loader.gitea import read_json
from openqabot.loader.incrementconfig import IncrementConfig
from responses import GET


# Fake Namespace for IncrementApprover initialization
class Namespace(NamedTuple):
    dry: bool
    token: str
    openqa_instance: str
    accepted: bool
    request_id: int
    project_base: str
    build_project_suffix: str
    diff_project_suffix: str
    distri: str
    version: str
    flavor: str
    schedule: bool
    reschedule: bool
    build_listing_sub_path: str
    build_regex: str
    product_regex: str
    fake_data: bool
    increment_config: str
    packages: list
    archs: set
    settings: dict
    additional_builds: list


# define fake data
class ReviewState(NamedTuple):
    state: str
    by_group: str


openqa_url = "http://openqa-instance/api/v1/isos/job_stats"


@dataclass
class Action:
    tgt_project: str
    src_project: str
    src_package: str


@dataclass
class Repo:
    name: str
    arch: str


@pytest.fixture
def fake_no_jobs() -> None:
    responses.add(GET, openqa_url, json={})


@pytest.fixture
def fake_pending_jobs() -> None:
    responses.add(GET, openqa_url, json={"scheduled": {}, "running": {}})


@pytest.fixture
def fake_not_ok_jobs() -> None:
    responses.add(
        GET,
        openqa_url,
        json={"done": {"passed": {"job_ids": [20]}, "failed": {"job_ids": [21]}}},
    )


@pytest.fixture
def fake_ok_jobs() -> None:
    responses.add(
        GET,
        openqa_url,
        json={"done": {"passed": {"job_ids": [22]}, "softfailed": {"job_ids": [24]}}},
    )


@pytest.fixture
def fake_product_repo() -> None:
    responses.add(
        GET,
        OBS_DOWNLOAD_URL + "/OBS:/PROJECT:/TEST/product/?jsontable=1",
        json=read_json("test-product-repo"),
    )


def fake_osc_get_config(override_apiurl: str) -> None:
    assert override_apiurl == OBS_URL


def fake_get_request_list(url: str, project: str, **_kwargs: Any) -> list[osc.core.Request]:
    assert url == OBS_URL
    assert project == "OBS:PROJECT:TEST"
    req = osc.core.Request()
    req.reqid = 42
    req.state = "review"
    req.reviews = [ReviewState("review", OBS_GROUP)]
    req.actions = [
        Action(
            tgt_project="SUSE:Products:SLE-Product-SLES:16.0:TEST",
            src_project="SUSE:Products:SLE-Product-SLES:16.0",
            src_package="000productcompose:sles_aarch64",
        )
    ]
    return [req]


def fake_get_repos_of_project(url: str, prj: str) -> list[Repo]:
    assert url == OBS_URL
    if prj == "SUSE:Products:SLE-Product-SLES:16.0:TEST":
        return [Repo("images", "local")]
    # example for "SUSE:Products:SLE-Product-SLES:16.0":
    return [Repo("product", "local")]


def fake_get_binarylist(url: str, prj: str, repo: str, arch: str, package: str) -> list[str]:
    assert url == OBS_URL
    assert package == "000productcompose:sles_aarch64"
    assert arch == "local"
    if prj == "SUSE:Products:SLE-Product-SLES:16.0:TEST" and repo == "images":
        return ["SLES-16.0-aarch64-Build160.4-Source.report", "foo"]
    # example for prj == "SUSE:Products:SLE-Product-SLES:16.0" and repo == "product":
    return ["SLES-16.0-aarch64-Build160.4-Source.report", "bar"]


def fake_get_binary_file(  # noqa: PLR0917
    url: str, prj: str, repo: str, arch: str, package: str, filename: str, target_filename: str
) -> None:
    assert url == OBS_URL
    assert package == "000productcompose:sles_aarch64"
    assert arch == "local"
    assert repo in {"images", "product"}
    assert filename == "SLES-16.0-aarch64-Build160.4-Source.report"
    Path(target_filename).symlink_to(Path(f"responses/source-report-{prj}.xml").absolute())


def fake_change_review_state(apiurl: str, reqid: str, newstate: str, by_group: str, message: str) -> None:
    assert apiurl == OBS_URL
    assert reqid == "42"
    assert newstate == "accepted"
    assert by_group == OBS_GROUP
    assert message == "All 2 jobs on openQA have passed/softfailed"


def prepare_approver(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    schedule: bool = False,
    reschedule: bool = False,
    diff_project_suffix: str = "none",
    test_env_var: str = "",
    config: IncrementConfig | None = None,
    request_id: int | None = None,
) -> IncrementApprover:
    os.environ["CI_JOB_URL"] = test_env_var
    caplog.set_level(logging.DEBUG, logger="bot.increment_approver")
    monkeypatch.setattr(osc.core, "get_request_list", fake_get_request_list)
    monkeypatch.setattr(osc.core, "change_review_state", fake_change_review_state)
    monkeypatch.setattr(osc.conf, "get_config", fake_osc_get_config)
    args = Namespace(
        dry=False,
        token="not-secret",
        openqa_instance=urlparse("http://openqa-instance"),
        accepted=True,
        request_id=request_id,
        project_base="OBS:PROJECT",
        build_project_suffix="TEST",
        diff_project_suffix=diff_project_suffix,
        distri="sle",
        version="16.0",
        flavor="Online-Increments",
        schedule=schedule,
        reschedule=reschedule,
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
    return IncrementApprover(args)


def run_approver(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    schedule: bool = False,
    reschedule: bool = False,
    diff_project_suffix: str = "none",
    test_env_var: str = "",
    config: IncrementConfig | None = None,
    request_id: int | None = None,
) -> tuple[int, list]:
    jobs = []
    monkeypatch.setattr(
        openqabot.openqa.openQAInterface,
        "post_job",
        lambda _self, data: jobs.append(data),
    )
    increment_approver = prepare_approver(
        caplog,
        monkeypatch,
        schedule=schedule,
        reschedule=reschedule,
        diff_project_suffix=diff_project_suffix,
        test_env_var=test_env_var,
        config=config,
        request_id=request_id,
    )
    errors = increment_approver()
    return (errors, jobs)


@responses.activate
@pytest.mark.usefixtures("fake_ok_jobs", "fake_product_repo")
def test_approval_if_there_are_only_ok_openqa_jobs(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_approver(caplog, monkeypatch)
    last_message = [x[-1] for x in caplog.record_tuples][-1]
    assert "All 2 jobs on openQA have passed/softfailed" in last_message


@responses.activate
@pytest.mark.usefixtures("fake_ok_jobs", "fake_product_repo")
def test_skipping_if_rescheduling(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    run_approver(caplog, monkeypatch, reschedule=True)
    last_message = [x[-1] for x in caplog.record_tuples][-1]
    assert "have passed" not in last_message
    assert "Re-scheduling jobs for" in last_message


@responses.activate
@pytest.mark.usefixtures("fake_not_ok_jobs", "fake_ok_jobs", "fake_product_repo")
def test_skipping_with_failing_openqa_jobs_for_one_config(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    increment_approver = prepare_approver(caplog, monkeypatch)
    increment_approver.config.append(increment_approver.config[0])
    increment_approver()
    last_message = [x[-1] for x in caplog.record_tuples][-1]
    assert "have passed" not in last_message
    assert "ended up with result 'failed':\n - http://openqa-instance/tests/21" in last_message


@responses.activate
@pytest.mark.usefixtures("fake_no_jobs", "fake_product_repo")
def test_skipping_with_no_openqa_jobs(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
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
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
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
        expected_params = {
            "DISTRI": "sle",
            "VERSION": "16.0",
            "FLAVOR": "Online-Increments",
            "BUILD": "139.1",
            "ARCH": arch,
            "INCREMENT_REPO": "http://%REPO_MIRROR_HOST%/ibs/OBS:/PROJECT:/TEST/product",
            "__CI_JOB_URL": ci_job_url,
            "_ONLY_OBSOLETE_SAME_BUILD": "1",
            "_OBSOLETE": "1",
        }
        assert expected_params in jobs, f"{arch} jobs created"


def assert_run_with_extra_livepatching(errors: int, jobs: list, messages: list) -> None:
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
        "_OBSOLETE": "1",
        "_ONLY_OBSOLETE_SAME_BUILD": "1",
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
@pytest.mark.usefixtures("fake_no_jobs", "fake_product_repo")
def test_scheduling_extra_livepatching_builds_with_no_openqa_jobs(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Path("tests/fixtures/config-increment-approver/increment-definitions.yaml")
    configs = IncrementConfig.from_config_file(path)
    args = {
        "caplog": caplog,
        "monkeypatch": monkeypatch,
        "schedule": True,
        "diff_project_suffix": "PUBLISH/product",
        "config": next(configs),
    }
    (errors, jobs) = run_approver(**args)
    messages = [x[-1] for x in caplog.record_tuples]
    assert_run_with_extra_livepatching(errors, jobs, messages)

    config = next(configs)
    config.packages.append("foobar")  # make the filter for packages not match
    args["config"] = config
    (errors, jobs) = run_approver(**args)
    assert jobs == []
    assert any("filtered out via 'packages' or 'archs'" in m[-1] for m in caplog.record_tuples)


@responses.activate
@pytest.mark.usefixtures("fake_no_jobs", "fake_product_repo")
def test_scheduling_extra_livepatching_builds_based_on_source_report(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(osc.core, "get_repos_of_project", fake_get_repos_of_project)
    monkeypatch.setattr(osc.core, "get_binarylist", fake_get_binarylist)
    monkeypatch.setattr(osc.core, "get_binary_file", fake_get_binary_file)
    path = Path("tests/fixtures/config-increment-approver/increment-definitions.yaml")
    args = {
        "caplog": caplog,
        "monkeypatch": monkeypatch,
        "schedule": True,
        "diff_project_suffix": "source-report",
        "config": next(IncrementConfig.from_config_file(path)),
    }
    (errors, jobs) = run_approver(**args)
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Computing source report diff for request 42" in messages
    assert_run_with_extra_livepatching(errors, jobs, messages)


@responses.activate
@pytest.mark.usefixtures("fake_pending_jobs", "fake_product_repo")
def test_skipping_with_pending_openqa_jobs(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    run_approver(caplog, monkeypatch)
    messages = [x[-1] for x in caplog.record_tuples]
    assert (
        # ruff: noqa: E501 line-too-long
        "Skipping approval, some jobs on openQA for SLESv16.0 build 139.1@aarch64 of flavor Online-Increments are in pending states (running, scheduled)"
        in messages
    )


@responses.activate
@pytest.mark.usefixtures("fake_not_ok_jobs", "fake_product_repo")
def test_listing_not_ok_openqa_jobs(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_approver(caplog, monkeypatch)
    last_message = [x[-1] for x in caplog.record_tuples][-1]
    assert "The following openQA jobs ended up with result 'failed'" in last_message
    assert "http://openqa-instance/tests/21" in last_message
    assert "http://openqa-instance/tests/20" not in last_message


def test_config_parsing(caplog: pytest.LogCaptureFixture) -> None:
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


def test_specified_obs_request_not_found_skips_approval(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_request_from_api(apiurl: str, reqid: int) -> None:
        assert apiurl == OBS_URL
        assert reqid == "43"

    monkeypatch.setattr(osc.core.Request, "from_api", fake_request_from_api)
    run_approver(caplog, monkeypatch, request_id=43)
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Checking specified request 43" in messages
    assert "Skipping approval, no relevant requests in states new/review/accepted" in messages


def test_specified_obs_request_found_renders_request(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_request_from_api(apiurl: str, reqid: str) -> osc.core.Request:
        assert apiurl == OBS_URL
        assert reqid == "43"
        req = osc.core.Request()
        req.reqid = 43
        req.state = type("state", (), {"to_xml": lambda: True})
        req.reviews = [ReviewState("review", OBS_GROUP)]
        req.to_str = lambda: "<request />"
        return req

    monkeypatch.setattr(osc.core.Request, "from_api", fake_request_from_api)
    approver = prepare_approver(caplog, monkeypatch, request_id=43)
    approver._find_request_on_obs("foo")  # noqa: SLF001
    assert "Checking specified request 43" in caplog.text
    assert "<request />" in caplog.text


def test_config_parsing_from_args() -> None:
    class MinimalNs(NamedTuple):
        increment_config: str
        distri: str
        version: str
        flavor: str

    config = IncrementConfig.from_args(MinimalNs(None, "sle", "16.0", "Online-Increments"))
    assert len(config) == 1
    assert config[0].distri == "sle"
    assert config[0].version == "16.0"
    assert config[0].flavor == "Online-Increments"
    assert config[0].packages == []
    assert config[0].archs == set()
    assert config[0].settings == {}


def test_get_regex_match_invalid_pattern(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    approver = prepare_approver(caplog, monkeypatch)
    approver._get_regex_match("[", "some string")  # noqa: SLF001
    assert "Pattern `[` did not compile successfully" in caplog.text


def test_find_request_on_obs_with_request_id(caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request_from_api(apiurl: str, reqid: str) -> osc.core.Request:
        assert apiurl == OBS_URL
        assert reqid == "43"
        req = osc.core.Request()
        req.reqid = 43
        req.state = type("state", (), {"to_xml": lambda: True})
        req.reviews = [ReviewState("review", OBS_GROUP)]
        req.to_str = lambda: "<request />"
        return req

    monkeypatch.setattr(osc.core.Request, "from_api", fake_request_from_api)
    approver = prepare_approver(caplog, monkeypatch, request_id=43)
    approver._find_request_on_obs("foo")  # noqa: SLF001
    assert "Checking specified request 43" in caplog.text
    assert "<request />" in caplog.text
