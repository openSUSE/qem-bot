# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# ruff: noqa: S106 "Possible hardcoded password assigned to argument"
from __future__ import annotations

import logging
import os
import re
from argparse import Namespace
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NamedTuple
from unittest.mock import MagicMock
from urllib.parse import urlparse

import osc.core
import pytest
from pytest_mock import MockerFixture

import responses
from openqabot.config import BUILD_REGEX, OBS_DOWNLOAD_URL, OBS_GROUP, OBS_URL
from openqabot.errors import PostOpenQAError
from openqabot.incrementapprover import ApprovalStatus, IncrementApprover
from openqabot.loader.gitea import read_json
from openqabot.loader.incrementconfig import IncrementConfig
from openqabot.repodiff import Package
from openqabot.utils import merge_dicts
from responses import GET


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


def fake_openqa_responses_with_param_matching(additional_builds_json: dict) -> list[responses.BaseResponse]:
    list_of_params = []
    base_params = {"distri": "sle", "version": "16.0", "build": "139.1"}
    json_by_arch = {"aarch64": {}, "x86_64": {}, "s390x": {}, "ppc64le": {}}
    for flavor in ("Online-Increments", "Foo-Increments"):
        for arch, json in json_by_arch.items():
            list_of_params.append(({"arch": arch, "flavor": flavor}, json))
    list_of_params.append((
        {"arch": "x86_64", "flavor": "Additional-Foo-Increments", "build": "139.1-additional-build"},
        additional_builds_json,
    ))
    return [
        responses.add(
            GET,
            openqa_url,
            json=json,
            match=[responses.matchers.query_param_matcher(merge_dicts(base_params, params))],
        )
        for (params, json) in list_of_params
    ]


def make_passing_and_failing_job() -> dict:
    return {"done": {"passed": {"job_ids": [20]}, "failed": {"job_ids": [21]}}}


@pytest.fixture
def fake_no_jobs_with_param_matching() -> list[responses.BaseResponse]:
    return fake_openqa_responses_with_param_matching({})


@pytest.fixture
def fake_only_jobs_of_additional_builds_with_param_matching() -> list[responses.BaseResponse]:
    return fake_openqa_responses_with_param_matching(make_passing_and_failing_job())


@pytest.fixture
def fake_pending_jobs() -> None:
    responses.add(GET, openqa_url, json={"scheduled": {}, "running": {}})


@pytest.fixture
def fake_not_ok_jobs() -> None:
    responses.add(GET, openqa_url, json=make_passing_and_failing_job())


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


@pytest.fixture
def fake_package_diff(mocker: MockerFixture) -> None:
    # assume the package "foo" has changed for x86_64 only (so additional_builds will only lead to an addtional
    # build on x86_64)
    package_diff = defaultdict(set)
    package_diff["x86_64"] = {Package("foo", "1", "2", "3", "x86_64")}
    mocker.patch("openqabot.incrementapprover.IncrementApprover._package_diff", return_value=package_diff)


def fake_osc_get_config(override_apiurl: str) -> None:
    assert override_apiurl == OBS_URL


def fake_get_request_list(url: str, project: str, **_kwargs: Any) -> list[osc.core.Request]:
    assert url == OBS_URL
    assert "OBS:PROJECT" in project
    req = osc.core.Request()
    req.reqid = 42
    req.state = "review"
    req.reviews = [ReviewState("review", OBS_GROUP)]
    req.actions = [
        Action(
            tgt_project="SUSE:Products:SLE-Product-SLES:16.0",
            src_project="SUSE:Products:SLE-Product-SLES:16.0:TEST",
            src_package="000productcompose:sles_aarch64",
        )
    ]
    return [req]


def fake_get_repos_of_project(url: str, prj: str) -> list[Repo]:
    assert url == OBS_URL
    if prj == "SUSE:Products:SLE-Product-SLES:16.0:TEST":
        return [Repo("product", "local")]
    # example for "SUSE:Products:SLE-Product-SLES:16.0":
    return [Repo("images", "local")]


def fake_get_binarylist(url: str, prj: str, repo: str, arch: str, package: str) -> list[str]:
    assert url == OBS_URL
    assert package == "000productcompose:sles_aarch64"
    assert arch == "local"
    if prj == "SUSE:Products:SLE-Product-SLES:16.0:TEST" and repo == "product":
        return ["SLES-16.0-aarch64-Build160.4-Source.report", "foo"]
    # example for prj == "SUSE:Products:SLE-Product-SLES:16.0" and repo == "images":
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
    assert message == "All 2 openQA jobs have passed/softfailed"


def prepare_approver(
    caplog: pytest.LogCaptureFixture,
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


def prepare_approver_with_additional_config(caplog: pytest.LogCaptureFixture) -> IncrementApprover:
    increment_approver = prepare_approver(caplog)
    product_regex = "^SLES$"  # only consider "SLES" and not "SLES-SAP" which is also in "test-product-repo.json"
    increment_approver.config[0].product_regex = product_regex
    additional_config = IncrementConfig(
        distri="sle",
        version="16.0",
        flavor="Online-Increments",
        project_base="OBS:PROJECT",
        build_project_suffix="TEST",
        diff_project_suffix="mocked",
        build_listing_sub_path="product",
        product_regex="^SLES$",
        build_regex=BUILD_REGEX,
        settings={"FLAVOR": "Foo-Increments"},
        additional_builds=[
            {
                "build_suffix": "additional-build",
                "package_name_regex": ".*",
                "settings": {"FLAVOR": "Additional-Foo-Increments"},
            }
        ],
    )
    increment_approver.config.append(additional_config)
    assert len(increment_approver.config) == 2
    return increment_approver


def run_approver(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    *,
    schedule: bool = False,
    reschedule: bool = False,
    diff_project_suffix: str = "none",
    test_env_var: str = "",
    config: IncrementConfig | None = None,
    request_id: int | None = None,
) -> tuple[int, list]:
    jobs: list[Any] = []
    mock_post_job = MagicMock()
    mocker.patch("openqabot.openqa.openQAInterface.post_job", new=mock_post_job)
    increment_approver = prepare_approver(
        caplog,
        schedule=schedule,
        reschedule=reschedule,
        diff_project_suffix=diff_project_suffix,
        test_env_var=test_env_var,
        config=config,
        request_id=request_id,
    )
    errors = increment_approver()
    jobs = [call_args.args[0] for call_args in mock_post_job.call_args_list]
    return (errors, jobs)


@pytest.fixture(autouse=True)
def mock_osc(mocker: MockerFixture) -> None:
    mocker.patch("osc.core.get_request_list", side_effect=fake_get_request_list)
    mocker.patch("osc.core.change_review_state", side_effect=fake_change_review_state)
    mocker.patch("osc.conf.get_config", side_effect=fake_osc_get_config)


@responses.activate
@pytest.mark.usefixtures("fake_ok_jobs", "fake_product_repo")
def test_approval_if_there_are_only_ok_openqa_jobs(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    run_approver(mocker, caplog)
    assert "Approving OBS request ID '42': All 2 openQA jobs have passed/softfailed" in caplog.messages[-1]


@responses.activate
@pytest.mark.usefixtures("fake_ok_jobs", "fake_product_repo")
def test_skipping_if_rescheduling(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    run_approver(mocker, caplog, reschedule=True)
    last_message = caplog.messages[-1]
    assert "have passed" not in last_message
    assert "Re-scheduling jobs for" in last_message


@responses.activate
@pytest.mark.usefixtures("fake_not_ok_jobs", "fake_ok_jobs", "fake_product_repo")
def test_skipping_with_failing_openqa_jobs_for_one_config(caplog: pytest.LogCaptureFixture) -> None:
    increment_approver = prepare_approver(caplog)
    increment_approver.config.append(increment_approver.config[0])
    increment_approver()
    last_message = caplog.messages[-1]
    assert "have passed" not in last_message
    assert "ended up with result 'failed':\n - http://openqa-instance/tests/21" in last_message


@responses.activate
@pytest.mark.usefixtures("fake_product_repo", "fake_package_diff")
def test_skipping_with_no_openqa_jobs_verifying_that_expected_scheduled_products_are_considered(
    caplog: pytest.LogCaptureFixture,
    fake_no_jobs_with_param_matching: list[responses.Response],
) -> None:
    # configure increment approver with additional config to check whether scheduled products of all configs
    # are considered
    increment_approver = prepare_approver_with_additional_config(caplog)
    increment_approver()
    for resp in fake_no_jobs_with_param_matching:
        assert resp.call_count == 1, "every relevant scheduled product in openQA is checked exactly once"

    for arch in ("aarch64", "x86_64", "ppc64le", "s390x"):
        assert re.search(
            f"Skipping approval.*no relevant jobs.*SLESv16.0.*139.1@{arch}.*Online-Increments", caplog.text
        )
        if arch == "x86_64":
            expected_log_message = R"Skipping approval.*no relevant jobs"
            expected_log_message += ".*SLESv16.0.*139.1@x86_64.*Foo-Increments"
            expected_log_message += ".*SLESv16.0.*139.1-additional-build@x86_64.*Additional-Foo-Increments"
            assert re.search(
                expected_log_message,
                caplog.text,
            ), "the scheduled product for the additional_builds is considered for x86_64 as well"
        else:
            assert re.search(
                f"Skipping approval.*no relevant jobs.*SLESv16.0.*139.1@{arch}.*Foo-Increments", caplog.text
            ), "for archs other than x86_64 the additional_builds have no additional scheduled products to consider"
    assert "Not approving OBS request ID '42' for the following reasons:" in caplog.messages[-1]


@responses.activate
@pytest.mark.usefixtures("fake_product_repo", "fake_package_diff")
def test_skipping_with_only_jobs_of_additional_builds_present(
    caplog: pytest.LogCaptureFixture,
    fake_only_jobs_of_additional_builds_with_param_matching: list[responses.Response],
) -> None:
    increment_approver = prepare_approver_with_additional_config(caplog)
    increment_approver()
    for resp in fake_only_jobs_of_additional_builds_with_param_matching:
        assert resp.call_count == 1, "every relevant scheduled product in openQA is checked exactly once"

    for arch in ("aarch64", "x86_64", "ppc64le", "s390x"):
        assert re.search(
            f"Skipping approval.*no relevant jobs.*SLESv16.0.*139.1@{arch}.*Online-Increments", caplog.text
        )
        if arch != "x86_64":
            assert re.search(
                f"Skipping approval.*no relevant jobs.*SLESv16.0.*139.1@{arch}.*Foo-Increments", caplog.text
            ), "for archs other than x86_64 the additional_builds have no additional scheduled products to consider"
    assert "Not approving OBS request ID '42' for the following reasons:" in caplog.messages[-1]
    assert re.search(R".*openQA jobs.*with result 'failed':\n - http://openqa-instance/tests/21", caplog.messages[-1])


@responses.activate
@pytest.mark.usefixtures("fake_no_jobs", "fake_product_repo")
def test_scheduling_with_no_openqa_jobs(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    ci_job_url = "https://some/ci/job/url"
    (errors, jobs) = run_approver(mocker, caplog, schedule=True, test_env_var=ci_job_url)
    assert re.search(r"Skipping approval.*no relevant jobs", caplog.text)
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
    assert "Skipping approval: There are no relevant jobs" in "".join(messages)
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
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    path = Path("tests/fixtures/config-increment-approver/increment-definitions.yaml")
    configs = IncrementConfig.from_config_file(path)
    (errors, jobs) = run_approver(
        mocker, caplog, schedule=True, diff_project_suffix="PUBLISH/product", config=next(configs)
    )
    assert_run_with_extra_livepatching(errors, jobs, caplog.messages)

    config = next(configs)
    config.packages.append("foobar")  # make the filter for packages not match
    (errors, jobs) = run_approver(mocker, caplog, schedule=True, diff_project_suffix="PUBLISH/product", config=config)
    assert jobs == []
    assert "filtered out via 'packages' or 'archs'" in caplog.text


@responses.activate
@pytest.mark.usefixtures("fake_no_jobs", "fake_product_repo")
def test_scheduling_extra_livepatching_builds_based_on_source_report(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    path = Path("tests/fixtures/config-increment-approver/increment-definitions.yaml")
    configs = IncrementConfig.from_config_file(path)
    mocker.patch("osc.core.get_repos_of_project", side_effect=fake_get_repos_of_project)
    mocker.patch("osc.core.get_binarylist", side_effect=fake_get_binarylist)
    mocker.patch("osc.core.get_binary_file", side_effect=fake_get_binary_file)
    (errors, jobs) = run_approver(
        mocker, caplog, schedule=True, diff_project_suffix="source-report", config=next(configs)
    )
    assert "Computing source report diff for OBS request ID 42" in caplog.messages
    assert_run_with_extra_livepatching(errors, jobs, caplog.messages)


@responses.activate
@pytest.mark.usefixtures("fake_pending_jobs", "fake_product_repo")
def test_skipping_with_pending_openqa_jobs(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    run_approver(mocker, caplog)
    assert re.search(r"Skipping approval: Some jobs.*are in pending states \(running, scheduled\)", caplog.text)


@responses.activate
@pytest.mark.usefixtures("fake_not_ok_jobs", "fake_product_repo")
def test_listing_not_ok_openqa_jobs(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    run_approver(mocker, caplog)
    last_message = caplog.messages[-1]
    assert "The following openQA jobs ended up with result 'failed'" in last_message
    assert "http://openqa-instance/tests/21" in last_message
    assert "http://openqa-instance/tests/20" not in last_message


@responses.activate
@pytest.mark.usefixtures("fake_product_repo")
def test_specified_obs_request_not_found_skips_approval(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    def fake_request_from_api(apiurl: str, reqid: int) -> None:
        assert apiurl == OBS_URL
        assert reqid == 43

    mocker.patch("osc.core.Request.from_api", side_effect=fake_request_from_api)
    run_approver(mocker, caplog, request_id=43)
    assert "Checking specified request 43" in caplog.messages
    assert "Skipping approval: OBS:PROJECT:TEST: No relevant requests in states new/review/accepted" in caplog.messages


@responses.activate
@pytest.mark.usefixtures("fake_product_repo")
def test_specified_obs_request_found_renders_request(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    def fake_request_from_api(apiurl: str, reqid: int) -> osc.core.Request:
        assert apiurl == OBS_URL
        assert reqid == 43
        req = osc.core.Request()
        req.reqid = 43
        req.state = type("state", (), {"to_xml": lambda: True})
        req.reviews = [ReviewState("review", OBS_GROUP)]
        req.to_str = lambda: "<request />"  # type: ignore[invalid-assignment]
        return req

    mocker.patch("osc.core.Request.from_api", side_effect=fake_request_from_api)
    approver = prepare_approver(caplog, request_id=43)
    approver._find_request_on_obs("foo")  # noqa: SLF001
    assert "Checking specified request 43" in caplog.text
    assert "<request />" in caplog.text


@responses.activate
@pytest.mark.usefixtures("fake_product_repo")
def test_get_regex_match_invalid_pattern(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    approver._get_regex_match("[", "some string")  # noqa: SLF001
    assert "Pattern `[` did not compile successfully" in caplog.text


@responses.activate
@pytest.mark.usefixtures("fake_product_repo")
def test_find_request_on_obs_with_request_id(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:

    def fake_request_from_api(apiurl: str, reqid: int) -> osc.core.Request:
        assert apiurl == OBS_URL
        assert reqid == 43
        req = osc.core.Request()
        req.reqid = 43
        req.state = type("state", (), {"to_xml": lambda: True})
        req.reviews = [ReviewState("review", OBS_GROUP)]
        req.to_str = lambda: "<request />"  # type: ignore[invalid-assignment]
        return req

    mocker.patch("osc.core.Request.from_api", side_effect=fake_request_from_api)
    approver = prepare_approver(caplog, request_id=43)
    approver._find_request_on_obs("foo")  # noqa: SLF001
    assert "Checking specified request 43" in caplog.text
    assert "<request />" in caplog.text


@responses.activate
@pytest.mark.usefixtures("fake_product_repo")
def test_find_request_on_obs_caching(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    # We mock get_request_list to track call counts
    mock_get_requests = mocker.patch("osc.core.get_request_list", side_effect=fake_get_request_list)
    mocker.patch("osc.conf.get_config", side_effect=fake_osc_get_config)

    approver = prepare_approver(caplog)

    # First call for a project
    res1 = approver._find_request_on_obs("OBS:PROJECT:TEST")  # noqa: SLF001
    assert mock_get_requests.call_count == 1
    assert res1
    assert res1.reqid == 42

    # Second call for the same project - should hit the cache
    res2 = approver._find_request_on_obs("OBS:PROJECT:TEST")  # noqa: SLF001
    assert mock_get_requests.call_count == 1
    assert res1 == res2

    # Call for a different project - should miss the cache
    mock_get_requests.return_value = []
    approver._find_request_on_obs("OBS:PROJECT:OTHER")  # noqa: SLF001
    assert mock_get_requests.call_count == 2


def test_handle_approval_dry(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.INFO)
    args = Namespace(
        dry=True,
        token="token",
        openqa_instance=urlparse("http://instance.qa"),
        accepted=True,
        request_id=None,
        project_base="BASE",
        build_project_suffix="TEST",
        diff_project_suffix="none",
        distri="sle",
        version="any",
        flavor="any",
        schedule=False,
        reschedule=False,
        build_listing_sub_path="product",
        build_regex=BUILD_REGEX,
        product_regex=".*",
        fake_data=True,
        increment_config=None,
        packages=[],
        archs=set(),
        settings={},
        additional_builds=[],
    )
    mocker.patch("osc.conf.get_config")
    approver = IncrementApprover(args)
    req = mocker.Mock(spec=osc.core.Request)
    req.reqid = 123
    status = ApprovalStatus(req, ok_jobs={1}, reasons_to_disapprove=[])
    mock_osc = mocker.patch("osc.core.change_review_state")

    approver._handle_approval(status)  # noqa: SLF001
    mock_osc.assert_not_called()
    assert "Approving OBS request ID '123': All 1 openQA jobs have passed/softfailed" in caplog.text


def test_determine_build_info_no_match(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
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
    # mock row that won't match product_regex
    mocker.patch("openqabot.incrementapprover.retried_requests.get").return_value.json.return_value = {
        "data": [{"name": "SLES-16.0-x86_64-Build1.1-Source.report.spdx.json"}]
    }
    res = approver._determine_build_info(config)  # noqa: SLF001
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
    from openqabot.incrementapprover import BuildInfo

    build_info = BuildInfo("sle", "SLES", "16.0", "flavor", "arch", "1.1")
    res = approver._extra_builds_for_package(package, config, build_info)  # noqa: SLF001
    assert res is None


def test_schedule_jobs_dry(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    approver.args.dry = True
    from openqabot.incrementapprover import BuildInfo

    build_info = BuildInfo("sle", "SLES", "16.0", "flavor", "arch", "1.1")
    params = [{"BUILD": "1.1"}]
    mock_post = mocker.patch.object(approver.client, "post_job")
    res = approver._schedule_openqa_jobs(build_info, params)  # noqa: SLF001
    assert res == 0
    mock_post.assert_not_called()


def test_schedule_jobs_fail(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    from openqabot.incrementapprover import BuildInfo

    build_info = BuildInfo("sle", "SLES", "16.0", "flavor", "arch", "1.1")
    params = [{"BUILD": "1.1"}]
    mocker.patch.object(approver.client, "post_job", side_effect=PostOpenQAError)
    res = approver._schedule_openqa_jobs(build_info, params)  # noqa: SLF001
    assert res == 1


@responses.activate
@pytest.mark.usefixtures("fake_product_repo")
def test_find_request_on_obs_not_accepted(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    approver.args.accepted = False
    # verify that accepted state is NOT added to relevant_states
    mock_get_list = mocker.patch("openqabot.incrementapprover.IncrementApprover._get_obs_request_list", return_value=[])
    approver._find_request_on_obs("project")  # noqa: SLF001
    assert mock_get_list.call_args[1]["req_state"] == ("new", "review")


def test_package_diff_repo(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(distri="sle", version="any", flavor="any", project_base="BASE", diff_project_suffix="DIFF")
    mock_diff = mocker.patch("openqabot.incrementapprover.RepoDiff")
    mock_diff.return_value.compute_diff.return_value = [{"some": "diff"}, 1]
    res = approver._package_diff(None, config, "/product")  # noqa: SLF001
    assert res == {"some": "diff"}


def test_determine_build_info_missing_flavor_group(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    # custom regex without flavor group
    config = IncrementConfig(
        distri="sle",
        version="any",
        flavor="any",
        project_base="BASE",
        build_project_suffix="TEST",
        build_regex=r"(?P<product>SLES)-(?P<version>.*)-(?P<arch>.*)-Build(?P<build>.*)-Source.report.spdx.json",
    )
    mocker.patch("openqabot.incrementapprover.retried_requests.get").return_value.json.return_value = {
        "data": [{"name": "SLES-16.0-x86_64-Build1.1-Source.report.spdx.json"}]
    }
    res = approver._determine_build_info(config)  # noqa: SLF001
    assert len(res) == 1
    assert next(iter(res)).flavor == "Online-Increments"


def test_determine_build_info_filter_no_match(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    # config with filters that won't match the row's version
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
    res = approver._determine_build_info(config)  # noqa: SLF001
    assert res == set()


def test_package_diff_none(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(distri="sle", version="any", flavor="any", diff_project_suffix="none")
    res = approver._package_diff(None, config, "/product")  # noqa: SLF001
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
    res = approver._package_diff(None, config, "/product")  # noqa: SLF001
    assert res == {"cached": "diff"}


def test_package_diff_source_report_no_request(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    config = IncrementConfig(
        distri="sle", version="any", flavor="any", project_base="BASE", diff_project_suffix="source-report"
    )
    res = approver._package_diff(None, config, "/product")  # noqa: SLF001
    assert res == {}
    assert "Source report diff requested but no request found" in caplog.text


def test_extra_builds_package_version_regex_no_match(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)
    package = Package("foo", "1", "2", "3", "arch")
    config = IncrementConfig(
        distri="sle",
        version="any",
        flavor="any",
        additional_builds=[{"package_name_regex": "foo", "package_version_regex": "999", "build_suffix": "suffix"}],
    )
    from openqabot.incrementapprover import BuildInfo

    build_info = BuildInfo("sle", "SLES", "16.0", "flavor", "arch", "1.1")
    res = approver._extra_builds_for_package(package, config, build_info)  # noqa: SLF001
    assert res is None
