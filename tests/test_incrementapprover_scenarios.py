# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test increment approver scenarios."""

from __future__ import annotations

import logging
import re
from argparse import Namespace
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import osc.core
import pytest
from pytest_mock import MockerFixture

import responses
from openqabot.errors import AmbiguousApprovalStatusError
from openqabot.incrementapprover import IncrementApprover
from openqabot.loader.incrementconfig import IncrementConfig
from openqabot.types.increment import ApprovalStatus, BuildIdentifier, BuildInfo

from .helpers import (
    Action,
    ReviewState,
    fake_get_binary_file,
    fake_get_binarylist,
    fake_get_repos_of_project,
    prepare_approver,
    prepare_approver_with_additional_config,
    run_approver,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def fake_osc_request(mocker: MockerFixture) -> osc.core.Request:
    req = mocker.Mock(spec=osc.core.Request)
    req.reqid = "42"
    return req


@responses.activate
@pytest.mark.usefixtures("fake_ok_jobs", "fake_product_repo", "mock_osc")
def test_approval_if_there_are_only_ok_openqa_jobs(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    run_approver(mocker, caplog)
    assert (
        "Approving OBS request https://build.suse.de/request/show/42: All 2 openQA jobs have passed/softfailed"
        in caplog.messages[-1]
    )


@responses.activate
@pytest.mark.usefixtures("fake_ok_jobs", "fake_product_repo", "mock_osc")
def test_skipping_if_rescheduling(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    run_approver(mocker, caplog, reschedule=True)
    last_message = caplog.messages[-1]
    assert "have passed" not in last_message
    assert "Re-scheduling jobs for" in last_message


@responses.activate
@pytest.mark.usefixtures("fake_not_ok_jobs", "fake_ok_jobs", "fake_product_repo")
def test_skipping_with_failing_openqa_jobs_for_one_config(
    caplog: pytest.LogCaptureFixture, fake_openqa_url: str
) -> None:
    increment_approver = prepare_approver(caplog)
    increment_approver.config.append(increment_approver.config[0])
    increment_approver()
    last_message = caplog.messages[-1]
    assert "have passed" not in last_message
    assert f"ended up with result 'failed':\n - {fake_openqa_url}/tests/21" in last_message


@responses.activate
@pytest.mark.usefixtures("fake_product_repo", "fakeget_package_diff")
def test_skipping_with_no_openqa_jobs_verifying_that_expected_scheduled_products_are_considered(
    caplog: pytest.LogCaptureFixture,
    fake_no_jobs_with_param_matching: list[responses.Response],
) -> None:
    increment_approver = prepare_approver_with_additional_config(caplog)
    increment_approver()
    for resp in fake_no_jobs_with_param_matching:
        assert resp.call_count == 1

    for arch in ("aarch64", "x86_64", "ppc64le", "s390x"):
        assert re.search(
            f"Skipping approval.*no relevant jobs.*SLESv16.0.*139.1@{arch}.*Online-Increments", caplog.text
        )
    expected_log_message = R"Skipping approval.*no relevant jobs"
    expected_log_message += ".*SLESv16.0.*139.1@x86_64.*Foo-Increments"
    expected_log_message += ".*SLESv16.0.*139.1-additional-build@x86_64.*Additional-Foo-Increments"
    assert re.search(expected_log_message, caplog.text, re.DOTALL)
    assert re.search(r"Skipping approval.*no relevant jobs.*SLESv16.0.*139.1@s390x.*Foo-Increments", caplog.text)
    assert (
        "Not approving OBS request https://build.suse.de/request/show/42 for the following reasons:"
        in caplog.messages[-1]
    )


@responses.activate
@pytest.mark.usefixtures("fake_product_repo", "fakeget_package_diff")
def test_skipping_with_only_jobs_of_additional_builds_present(
    caplog: pytest.LogCaptureFixture,
    fake_only_jobs_of_additional_builds_with_param_matching: list[responses.Response],
) -> None:
    increment_approver = prepare_approver_with_additional_config(caplog)
    increment_approver()
    for resp in fake_only_jobs_of_additional_builds_with_param_matching:
        assert resp.call_count == 1

    assert re.search(r"Skipping approval.*no relevant jobs.*SLESv16.0.*139.1@x86_64.*Online-Increments", caplog.text)
    assert re.search(r"Skipping approval.*no relevant jobs.*SLESv16.0.*139.1@ppc64le.*Foo-Increments", caplog.text)
    assert (
        "Not approving OBS request https://build.suse.de/request/show/42 for the following reasons:"
        in caplog.messages[-1]
    )
    assert re.search(R".*openQA jobs.*with result 'failed':\n - http://instance.qa/tests/21", caplog.messages[-1])


@responses.activate
@pytest.mark.usefixtures("fake_no_jobs", "fake_product_repo")
def test_scheduling_with_no_openqa_jobs(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    ci_job_url = "https://some/ci/job/url"
    (errors, jobs) = run_approver(mocker, caplog, schedule=True, test_env_var=ci_job_url)
    assert re.search(r"Skipping approval.*no relevant jobs", caplog.text)
    assert errors == 0
    for arch in ["x86_64", "aarch64", "ppc64le", "s390x"]:
        expected_params = {
            "DISTRI": "sle",
            "VERSION": "16.0",
            "FLAVOR": "Online-Increments",
            "BUILD": "139.1",
            "ARCH": arch,
            "PRODUCT": "SLES",
            "INCREMENT_REPO": "http://%REPO_MIRROR_HOST%/ibs/OBS:/PROJECT:/TEST/product",
            "__CI_JOB_URL": ci_job_url,
            "_ONLY_OBSOLETE_SAME_BUILD": "1",
            "_OBSOLETE": "1",
        }
        assert expected_params in jobs


def assert_run_with_extra_livepatching(errors: int, jobs: list, messages: list) -> None:
    assert "Skipping approval: There are no relevant jobs" in "".join(messages)
    assert errors == 0
    base_params = {
        "DISTRI": "sle",
        "VERSION": "16.0",
        "FLAVOR": "Online-Increments",
        "BUILD": "139.1",
        "PRODUCT": "SLES",
        "INCREMENT_REPO": "http://%REPO_MIRROR_HOST%/ibs/OBS:/PROJECT:/TEST/product",
        "FOO": "bar",
        "_OBSOLETE": "1",
        "_ONLY_OBSOLETE_SAME_BUILD": "1",
    }
    for arch in ["x86_64", "aarch64", "ppc64le"]:
        assert base_params | {"ARCH": arch} in jobs
    assert base_params | {"ARCH": "s390x"} not in jobs

    def assert_livepatch(flavor: str, build_suffix: str, kernel_version: str) -> None:
        expected_params = base_params | {
            "FLAVOR": flavor,
            "BUILD": f"139.1-{build_suffix}",
            "KERNEL_VERSION": kernel_version,
            "KGRAFT": "1",
        }
        assert expected_params | {"ARCH": "ppc64le"} in jobs

    assert_livepatch("Default-qcow-Updates", "kernel-livepatch-default-6.12.0-160000.5", "6.12.0-160000.5")
    assert_livepatch("Base-RT-Updates", "kernel-livepatch-rt-6.12.0-160000.5", "6.12.0-160000.5")
    assert base_params | {"ARCH": "aarch64"} in jobs


@responses.activate
@pytest.mark.usefixtures("fake_no_jobs", "fake_product_repo")
def test_scheduling_extra_livepatching_builds_with_no_openqa_jobs(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    path = Path("tests/fixtures/config-increment-approver/increment-definitions.yaml")
    configs = IncrementConfig.from_config_file(path, load_defaults=False)
    (errors, jobs) = run_approver(
        mocker, caplog, schedule=True, diff_project_suffix="PUBLISH/product", config=next(configs)
    )
    assert_run_with_extra_livepatching(errors, jobs, caplog.messages)

    config = next(configs)
    config.packages.append("foobar")
    (errors, jobs) = run_approver(mocker, caplog, schedule=True, diff_project_suffix="PUBLISH/product", config=config)
    assert jobs == []
    assert "filtered out via 'packages' or 'archs'" in caplog.text


@responses.activate
@pytest.mark.usefixtures("fake_no_jobs", "fake_product_repo")
def test_scheduling_extra_livepatching_builds_based_on_source_report(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    path = Path("tests/fixtures/config-increment-approver/increment-definitions.yaml")
    configs = IncrementConfig.from_config_file(path, load_defaults=False)
    mocker.patch("osc.core.get_repos_of_project", side_effect=fake_get_repos_of_project)
    mocker.patch("osc.core.get_binarylist", side_effect=fake_get_binarylist)
    mocker.patch("osc.core.get_binary_file", side_effect=fake_get_binary_file)
    (errors, jobs) = run_approver(
        mocker, caplog, schedule=True, diff_project_suffix="source-report", config=next(configs)
    )
    assert "Computing source report diff for OBS request https://build.suse.de/request/show/42" in caplog.messages
    assert_run_with_extra_livepatching(errors, jobs, caplog.messages)


@responses.activate
@pytest.mark.usefixtures("fake_pending_jobs", "fake_product_repo")
def test_skipping_with_pending_openqa_jobs(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    run_approver(mocker, caplog)
    assert re.search(r"Skipping approval: Some jobs.*are in pending states \(running, scheduled\)", caplog.text)


@responses.activate
@pytest.mark.usefixtures("fake_not_ok_jobs", "fake_product_repo")
def test_listing_not_ok_openqa_jobs(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture, fake_openqa_url: str
) -> None:
    run_approver(mocker, caplog)
    last_message = caplog.messages[-1]
    assert "The following openQA jobs ended up with result 'failed'" in last_message
    assert f"{fake_openqa_url}/tests/21" in last_message
    assert f"{fake_openqa_url}/tests/20" not in last_message


def test_evaluate_list_of_openqa_job_results(
    caplog: pytest.LogCaptureFixture, fake_osc_request: osc.core.Request, fake_openqa_url: str
) -> None:
    approver = prepare_approver(caplog)
    results = [
        {"done": {"passed": {"job_ids": [1]}, "failed": {"job_ids": [2]}}},
        {"done": {"softfailed": {"job_ids": [3]}, "incomplete": {"job_ids": [4]}}},
    ]
    ok_jobs, reasons, jobs = approver.evaluate_list_of_openqa_job_results(results, fake_osc_request)
    assert ok_jobs == {1, 3}
    assert len(jobs) == 4
    assert any(f"result 'failed':\n - {fake_openqa_url}/tests/2" in r for r in reasons)
    assert any(f"result 'incomplete':\n - {fake_openqa_url}/tests/4" in r for r in reasons)


def test_check_unique_jobid_request_pair_all_jobs_unique(
    caplog: pytest.LogCaptureFixture, fake_osc_request: osc.core.Request
) -> None:
    approver = prepare_approver(caplog)
    approver.unique_jobid_request_pair[1] = 43
    approver.check_unique_jobid_request_pair([2], fake_osc_request)
    assert approver.unique_jobid_request_pair[2] == fake_osc_request.reqid


def test_check_unique_jobid_request_pair_ambiguity_found(
    caplog: pytest.LogCaptureFixture, fake_osc_request: osc.core.Request
) -> None:
    approver = prepare_approver(caplog)
    approver.unique_jobid_request_pair[1] = 43
    with pytest.raises(AmbiguousApprovalStatusError):
        approver.check_unique_jobid_request_pair([1], fake_osc_request)


def test_handle_approval_valid_request_id(caplog: pytest.LogCaptureFixture, fake_osc_request: osc.core.Request) -> None:
    approver = prepare_approver(caplog)
    status = ApprovalStatus(
        fake_osc_request, ok_jobs={1, 2}, reasons_to_disapprove=[], processed_jobs=set(), builds=set(), jobs=[]
    )

    approver.handle_approval(status)
    assert (
        "Approving OBS request https://build.suse.de/request/show/42: All 2 openQA jobs have passed/softfailed"
        in caplog.text
    )


def test_handle_approval_disapprove(caplog: pytest.LogCaptureFixture, fake_osc_request: osc.core.Request) -> None:
    approver = prepare_approver(caplog)
    status = ApprovalStatus(
        fake_osc_request,
        ok_jobs=set(),
        reasons_to_disapprove=["failed jobs"],
        processed_jobs=set(),
        builds=set(),
        jobs=[],
    )

    approver.handle_approval(status)
    assert "Not approving OBS request https://build.suse.de/request/show/42 for the following reasons:" in caplog.text
    assert "failed jobs" in caplog.text


def make_test_config(suffix: str, product: str, arch: str) -> IncrementConfig:
    test_build_regex = (
        r"(?P<product>.*?)-(?P<version>[\d\.]+)-(?P<flavor>\D+[^\-]*?)-(?P<arch>[^\-]*?)-Build(?P<build>.*?)\.spdx.json"
    )
    return IncrementConfig(
        distri="any",
        version="any",
        flavor="any",
        project_base="",
        build_project_suffix=suffix,
        build_listing_sub_path="product",
        build_regex=test_build_regex,
        product_regex=f"^{product}$",
        flavor_suffix="Increments",
        version_regex=r"[\d.]+",
        archs={arch},
    )


def test_skipping_with_mismatching_package(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    """Test skipping when packages are filtered out."""
    # This should trigger line 431-432 in incrementapprover.py
    caplog.set_level("INFO")
    configs = [make_test_config("TEST", "SLES", "x86_64")]
    configs[0].packages = ["nonexistent-package"]

    with patch("openqabot.incrementapprover.load_build_info") as mock_load:
        mock_load.return_value = [BuildInfo("sle", "SLES", "16.0", "Online-Increments", "x86_64", "139.1")]

        approver = IncrementApprover(
            Namespace(
                dry=True,
                token="token",
                gitea_token=None,
                accepted=True,
                request_id=None,
                fake_data=True,
                schedule=False,
                reschedule=False,
                increment_config=None,
                distri="any",
                version="any",
                flavor="any",
            )
        )
        req = mocker.Mock(spec=osc.core.Request)
        req.reqid = "42"
        # mock get_package_diff to return empty diff
        mocker.patch.object(approver, "get_package_diff", return_value=defaultdict(set))
        approver.process_request_for_config(req, configs[0])

    assert "Skipping" in caplog.text
    assert "filtered out via 'packages' or 'archs' setting" in caplog.text


@pytest.fixture
def mock_osc_requests(mocker: MockerFixture) -> None:
    def fake_get_request_list(_url: str, project: str, **_kwargs: Any) -> list[osc.core.Request]:
        req = osc.core.Request()
        req.state = "review"
        req.reviews = [ReviewState("review", "qam-openqa")]
        if "SL-Micro" in project:
            req.reqid = "399766"
        else:
            req.reqid = "399799"
        req.actions = [Action(tgt_project="TGT", src_project=project, src_package="PKG")]
        return [req]

    mocker.patch("osc.core.get_request_list", side_effect=fake_get_request_list)
    mocker.patch("osc.core.change_review_state")
    mocker.patch("osc.conf.get_config")

    def fake_from_api(_url: str, reqid: int) -> osc.core.Request:
        req = osc.core.Request()
        req.reqid = str(reqid)
        if str(reqid) == "399766":
            prj = "SUSE:SLFO:Products:SL-Micro:6.2:ToTest"
        else:
            prj = "SUSE:SLFO:Products:SLES:16.0:TEST"
        req.actions = [Action(tgt_project="TGT", src_project=prj, src_package="PKG")]
        return req

    mocker.patch("osc.core.Request.from_api", side_effect=fake_from_api)


@pytest.mark.usefixtures("mock_osc_requests")
def test_issue_194074_repro(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    config_sl_micro = make_test_config("SUSE:SLFO:Products:SL-Micro:6.2:ToTest", "SL-Micro", "x86_64")
    config_sles = make_test_config("SUSE:SLFO:Products:SLES:16.0:TEST", "SLES", "aarch64")

    build_info_sl_micro = BuildInfo("any", "SL-Micro", "6.2", "Default-qcow-Increments", "x86_64", "61.24")
    build_info_sles = BuildInfo("any", "SLES", "16.0", "Minimal-VM-Increments", "aarch64", "180.15")

    with (
        patch("openqabot.incrementapprover.load_build_info") as mock_load,
        patch("openqabot.openqa.OpenQAInterface.get_scheduled_product_stats") as mock_stats,
    ):
        mock_load.side_effect = lambda config, *_: (
            {build_info_sl_micro} if "SL-Micro" in config.product_regex else {build_info_sles}
        )
        mock_stats.side_effect = lambda p: {
            "done": {"failed": {"job_ids": [20724745 if p["product"] == "SL-Micro" else 20753853]}}
        }

        increment_approver = prepare_approver(caplog)
        increment_approver.config = [config_sl_micro, config_sles]
        increment_approver()

    log_399766 = [
        m
        for m in caplog.messages
        if "OBS request https://build.suse.de/request/show/399766" in m and "Not approving" in m
    ]
    assert len(log_399766) == 1
    assert "20724745" in log_399766[0]
    assert "20753853" not in log_399766[0]

    log_399799 = [
        m
        for m in caplog.messages
        if "OBS request https://build.suse.de/request/show/399799" in m and "Not approving" in m
    ]
    assert len(log_399799) == 1
    assert "20753853" in log_399799[0]
    assert "20724745" not in log_399799[0]


@pytest.mark.usefixtures("mock_osc_requests")
def test_issue_194074_specific_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    config_sl_micro = make_test_config("SUSE:SLFO:Products:SL-Micro:6.2:ToTest", "SL-Micro", "x86_64")
    config_sles = make_test_config("SUSE:SLFO:Products:SLES:16.0:TEST", "SLES", "aarch64")

    build_info_sl_micro = BuildInfo("any", "SL-Micro", "6.2", "Default-qcow-Increments", "x86_64", "61.24")

    with (
        patch("openqabot.incrementapprover.load_build_info") as mock_load,
        patch("openqabot.openqa.OpenQAInterface.get_scheduled_product_stats") as mock_stats,
    ):
        mock_load.return_value = {build_info_sl_micro}
        mock_stats.return_value = {"done": {"passed": {"job_ids": [20724745]}}}

        increment_approver = prepare_approver(caplog, request_id=399766)
        increment_approver.config = [config_sl_micro, config_sles]
        increment_approver()

    assert "Found product increment request on SUSE:SLFO:Products:SL-Micro:6.2:ToTest: 399766" in caplog.messages
    assert (
        "Approving OBS request https://build.suse.de/request/show/399766: All 1 openQA jobs have passed/softfailed"
        in caplog.messages
    )
    assert any(
        "Skipping config SUSE:SLFO:Products:SLES:16.0:TEST as it does not match request 399766" in m
        for m in caplog.messages
    )


@pytest.mark.usefixtures("mock_osc_requests")
def test_issue_194074_specific_request_sles(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    config_sl_micro = make_test_config("SUSE:SLFO:Products:SL-Micro:6.2:ToTest", "SL-Micro", "x86_64")
    config_sles = make_test_config("SUSE:SLFO:Products:SLES:16.0:TEST", "SLES", "aarch64")

    build_info_sles = BuildInfo("any", "SLES", "16.0", "Minimal-VM-Increments", "aarch64", "180.15")

    with (
        patch("openqabot.incrementapprover.load_build_info") as mock_load,
        patch("openqabot.openqa.OpenQAInterface.get_scheduled_product_stats") as mock_stats,
    ):
        mock_load.return_value = {build_info_sles}
        mock_stats.return_value = {"done": {"passed": {"job_ids": [20753853]}}}

        increment_approver = prepare_approver(caplog, request_id=399799)
        increment_approver.config = [config_sl_micro, config_sles]
        increment_approver()

    assert "Found product increment request on SUSE:SLFO:Products:SLES:16.0:TEST: 399799" in caplog.messages
    assert (
        "Approving OBS request https://build.suse.de/request/show/399799: All 1 openQA jobs have passed/softfailed"
        in caplog.messages
    )
    assert any(
        "Skipping config SUSE:SLFO:Products:SL-Micro:6.2:ToTest as it does not match request 399799" in m
        for m in caplog.messages
    )


@responses.activate
@pytest.mark.usefixtures("fake_product_repo", "mock_osc")
def test_approval_if_failing_jobs_are_in_development_group(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture, fake_openqa_url_job_stat: str
) -> None:
    # 1. Setup: a failed job exists in job_stats
    responses.add(
        responses.GET,
        fake_openqa_url_job_stat,
        json={"done": {"failed": {"job_ids": [123]}}},
    )

    # 2. Mock OpenQAInterface.get_single_job to return job details
    # and OpenQAInterface.is_devel_group to return True for its group_id
    mock_job = {
        "id": 123,
        "group": "Development Group",
        "group_id": 9,
        "result": "failed",
    }
    # 3. Run IncrementApprover
    increment_approver = prepare_approver(caplog)
    increment_approver.client.get_single_job = mocker.Mock(return_value=mock_job)
    increment_approver.client.is_devel_group = mocker.Mock(return_value=True)
    increment_approver()

    # 4. Verification:
    # Since the only job was in a development group, it should be ignored.
    # The IncrementApprover should report "No jobs scheduled for ..."
    # because the failed job was filtered out upfront.
    assert "Not approving OBS request https://build.suse.de/request/show/42 for the following reasons:" in caplog.text
    assert "No jobs scheduled for" in caplog.text


@responses.activate
@pytest.mark.usefixtures("fake_product_repo", "mock_osc")
def test_approval_with_mixed_jobs_development_ignored(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture, fake_openqa_url_job_stat: str
) -> None:
    # 1. Setup: one failed (devel) and one passed (prod) job
    responses.add(
        responses.GET,
        fake_openqa_url_job_stat,
        json={"done": {"failed": {"job_ids": [123]}, "passed": {"job_ids": [456]}}},
    )

    def mock_get_single_job(job_id: int) -> dict[str, Any]:
        if job_id == 123:
            return {"id": 123, "group": "Development", "group_id": 9, "result": "failed"}
        return {"id": 456, "group": "Production", "group_id": 1, "result": "passed"}

    def mock_is_devel_group(group_id: int) -> bool:
        return group_id == 9

    mock_osc_approve = mocker.patch("osc.core.change_review_state")

    # 3. Run IncrementApprover
    increment_approver = prepare_approver(caplog)
    increment_approver.client.get_single_job = mocker.Mock(side_effect=mock_get_single_job)
    increment_approver.client.is_devel_group = mocker.Mock(side_effect=mock_is_devel_group)
    increment_approver()

    # 4. Verification:
    # Job 123 (failed) is ignored. Job 456 (passed) is counted.
    # The request should be approved because all RELEVANT jobs passed.
    mock_osc_approve.assert_called()
    # The message should say "All 1 openQA jobs have passed/softfailed"
    # because only one job (456) was considered relevant.
    _, kwargs = mock_osc_approve.call_args
    assert "All 1 openQA jobs have passed/softfailed" in kwargs["message"]
    assert (
        "Approving OBS request https://build.suse.de/request/show/42: All 1 openQA jobs have passed/softfailed"
        in caplog.text
    )


@responses.activate
@pytest.mark.usefixtures("fake_product_repo", "mock_osc")
def test_approval_if_running_jobs_are_in_development_group(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture, fake_openqa_url_job_stat: str
) -> None:
    # 1. Setup: a running job in devel group and a passed job in prod group
    responses.add(
        responses.GET,
        fake_openqa_url_job_stat,
        json={"running": {"some_job": {"job_ids": [123]}}, "done": {"passed": {"job_ids": [456]}}},
    )

    def mock_get_single_job(job_id: int) -> dict[str, Any]:
        if job_id == 123:
            return {"id": 123, "group": "Development", "group_id": 9, "state": "running"}
        return {"id": 456, "group": "Production", "group_id": 1, "state": "done", "result": "passed"}

    def mock_is_in_devel_group(job: dict[str, Any]) -> bool:
        return "Development" in job.get("group", "")

    mock_osc_approve = mocker.patch("osc.core.change_review_state")

    increment_approver = prepare_approver(caplog)
    increment_approver.client.get_single_job = mocker.Mock(side_effect=mock_get_single_job)
    increment_approver.client.is_in_devel_group = mocker.Mock(side_effect=mock_is_in_devel_group)
    increment_approver()

    # 4. Verification:
    # Job 123 (running) is ignored. Job 456 (passed) is counted.
    # The request should be approved.
    assert "All 1 openQA jobs have passed/softfailed" in caplog.text
    mock_osc_approve.assert_called()


def test_handle_approval_with_comment_flag(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture, fake_osc_request: osc.core.Request
) -> None:
    approver = prepare_approver(caplog)
    approver.comment = True
    approver.args.dry = False
    mock_replace = mocker.patch.object(approver.commenter, "osc_comment_on_request")
    mocker.patch.object(approver, "approve_on_obs")
    status = ApprovalStatus(
        fake_osc_request,
        ok_jobs={1, 2},
        reasons_to_disapprove=[],
        processed_jobs=set(),
        builds={BuildIdentifier("fake_build", "fake_distri", "fake_version")},
        jobs=[{"build": "fake_build", "distri": "fake_distri", "version": "fake_version", "status": "passed"}],
    )

    approver.handle_approval(status)

    mock_replace.assert_called_once()
    args = mock_replace.call_args[0]
    assert args[0] == "42"
    assert args[2] == "passed"
    assert "fake_build" in args[1]
