from collections import namedtuple
from typing import Dict, Optional, List
from pathlib import Path
from urllib.parse import urlparse
import os
import logging

from responses import GET
import osc.conf
import osc.core
import pytest
import responses

import openqabot
from openqabot import BUILD_REGEX, OBS_URL, OBS_DOWNLOAD_URL, OBS_GROUP
from openqabot.loader.gitea import read_json
from openqabot.incrementapprover import IncrementApprover, IncrementConfig

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
        "additional_builds",
    ),
)

# define fake data
ReviewState = namedtuple("ReviewState", ("state", "by_group"))
openqa_url = "http://openqa-instance/api/v1/isos/job_stats"


@pytest.fixture(scope="function")
def fake_no_jobs(request):
    responses.add(GET, openqa_url, json={})


@pytest.fixture(scope="function")
def fake_pending_jobs(request):
    responses.add(GET, openqa_url, json={"scheduled": {}, "running": {}})


@pytest.fixture(scope="function")
def fake_not_ok_jobs(request):
    responses.add(
        GET,
        openqa_url,
        json={"done": {"passed": {"job_ids": [20]}, "failed": {"job_ids": [21]}}},
    )


@pytest.fixture(scope="function")
def fake_ok_jobs(request):
    responses.add(
        GET,
        openqa_url,
        json={"done": {"passed": {"job_ids": [20]}, "softfailed": {"job_ids": [21]}}},
    )


@pytest.fixture(scope="function")
def fake_product_repo(request):
    responses.add(
        GET,
        OBS_DOWNLOAD_URL + "/OBS:/PROJECT:/TEST/product/?jsontable=1",
        json=read_json("test-product-repo"),
    )


def fake_osc_get_config(override_apiurl: str):
    assert override_apiurl == OBS_URL


def fake_get_request_list(url: str, project: str, req_state: List[str]) -> List[osc.core.Request]:
    assert url == OBS_URL
    assert project == "OBS:PROJECT:TEST"
    req = osc.core.Request()
    req.reqid = 42
    req.state = "review"
    req.reviews = [ReviewState("review", OBS_GROUP)]
    return [req]


def fake_change_review_state(apiurl: str, reqid: str, newstate: str, by_group: str, message: str):
    assert apiurl == OBS_URL
    assert reqid == "42"
    assert newstate == "accepted"
    assert by_group == OBS_GROUP
    assert message == "All 2 jobs on openQA have passed/softfailed"


def run_approver(
    caplog,
    monkeypatch,
    schedule: bool = False,
    diff_project_suffix: str = "none",
    test_env_var: str = "",
    config: Optional[IncrementConfig] = None,
):
    jobs = []
    os.environ["CI_JOB_URL"] = test_env_var
    caplog.set_level(logging.DEBUG, logger="bot.increment_approver")
    monkeypatch.setattr(osc.core, "get_request_list", fake_get_request_list)
    monkeypatch.setattr(osc.core, "change_review_state", fake_change_review_state)
    monkeypatch.setattr(osc.conf, "get_config", fake_osc_get_config)
    monkeypatch.setattr(
        openqabot.openqa.openQAInterface,
        "post_job",
        lambda self, data: jobs.append(data),
    )
    args = _namespace(
        False,
        "not-secret",
        urlparse("http://openqa-instance"),
        True,
        None,
        "OBS:PROJECT",
        "TEST",
        diff_project_suffix,
        "sle",
        "16.0",
        "Online-Increments",
        schedule,
        False,
        "product",
        BUILD_REGEX,
        ".*",
        True,
        None,
        [] if config is None else config.packages,
        set() if config is None else config.archs,
        [] if config is None else config.additional_builds,
    )
    increment_approver = IncrementApprover(args)
    errors = increment_approver()
    return (errors, jobs)


@responses.activate
def test_skipping_with_no_openqa_jobs(caplog, fake_no_jobs, fake_product_repo, monkeypatch):
    run_approver(caplog, monkeypatch)
    messages = [x[-1] for x in caplog.record_tuples]
    assert (
        "Skipping approval, there are no relevant jobs on openQA for SLESv16.0 build 139.1@aarch64 of flavor Online-Increments"
        in messages
    )


@responses.activate
def test_scheduling_with_no_openqa_jobs(caplog, fake_no_jobs, fake_product_repo, monkeypatch):
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
            "INCIDENT_REPO": "http://download.suse.de/ibs/OBS:/PROJECT:/TEST/product",
            "__CI_JOB_URL": ci_job_url,
        } in jobs, f"{arch} jobs created"


@responses.activate
def test_scheduling_extra_livepatching_builds_with_no_openqa_jobs(caplog, fake_no_jobs, fake_product_repo, monkeypatch):
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
        "INCIDENT_REPO": "http://download.suse.de/ibs/OBS:/PROJECT:/TEST/product",
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
    assert (
        expected_livepatch_params | {"ARCH": "ppc64le"} in jobs
    ), f"additional kernel livepatch jobs of default flavor created"
    assert (
        expected_livepatch_rt_params | {"ARCH": "ppc64le"} in jobs
    ), f"additional kernel livepatch jobs of RT flavor created"
    assert (
        expected_livepatch_params | {"ARCH": "aarch64"} not in jobs
    ), "additional kernel livepatch jobs only created if package is new"


@responses.activate
def test_skipping_with_pending_openqa_jobs(caplog, fake_pending_jobs, fake_product_repo, monkeypatch):
    run_approver(caplog, monkeypatch)
    messages = [x[-1] for x in caplog.record_tuples]
    assert (
        "Skipping approval, some jobs on openQA for SLESv16.0 build 139.1@aarch64 of flavor Online-Increments are in pending states (running, scheduled)"
        in messages
    )


@responses.activate
def test_listing_not_ok_openqa_jobs(caplog, fake_not_ok_jobs, fake_product_repo, monkeypatch):
    run_approver(caplog, monkeypatch)
    last_message = [x[-1] for x in caplog.record_tuples][-1]
    assert "The following openQA jobs ended up with result 'failed'" in last_message
    assert "http://openqa-instance/tests/21" in last_message
    assert "http://openqa-instance/tests/20" not in last_message


@responses.activate
def test_approval_if_there_are_only_ok_openqa_jobs(caplog, fake_ok_jobs, fake_product_repo, monkeypatch):
    run_approver(caplog, monkeypatch)
    last_message = [x[-1] for x in caplog.record_tuples][-1]
    assert "All 2 jobs on openQA have passed/softfailed" in last_message


def test_config_parsing(caplog):
    path = Path("tests/fixtures/config-increment-approver/increment-definitions.yaml")
    configs = [*IncrementConfig.from_config_file(path)]
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
