# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Helper functions for tests."""

from __future__ import annotations

import logging
import os
import re
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple
from unittest.mock import MagicMock
from urllib.parse import urlparse

import osc.core

import responses
from openqabot.config import BUILD_REGEX, settings
from openqabot.incrementapprover import IncrementApprover
from openqabot.loader.incrementconfig import IncrementConfig
from openqabot.loader.qem import SubReq
from openqabot.utils import merge_dicts

if TYPE_CHECKING:
    import pytest
    from pytest_mock import MockerFixture


# define fake data
class ReviewState(NamedTuple):
    """Fake review state."""

    state: str
    by_group: str


openqa_url = "http://openqa-instance/api/v1/isos/job_stats"
obs_product_table_url = settings.obs_download_url + "/OBS:/PROJECT:/TEST/product/?jsontable=1"


@dataclass
class Action:
    """Fake action."""

    tgt_project: str
    src_project: str
    src_package: str


@dataclass
class Repo:
    """Fake repo."""

    name: str
    arch: str


def f_sub_approver(*_args: Any) -> list[SubReq]:
    return [
        SubReq(1, 100),
        SubReq(2, 200),
        SubReq(3, 300),
        SubReq(4, 400),
        SubReq(
            5,
            500,
            "git",
            "https://src.suse.de/products/SLFO/pulls/124",
            "18bfa2a23fb7985d5d0cc356474a96a19d91d2d8652442badf7f13bc07cd1f3d",
        ),
    ]


openqa_instance_url = urlparse("http://instance.qa")
args = Namespace(
    dry=False,
    token="123",
    all_submissions=False,
    openqa_instance=openqa_instance_url,
    incident=None,
    gitea_token=None,
)


def add_two_passed_response() -> None:
    responses.add(
        responses.GET,
        re.compile(f"{settings.qem_dashboard_url}api/jobs/.*/.*"),
        json=[{"status": "passed"}, {"status": "passed"}],
    )


def assert_submission_approved(messages: list[str], sub_str: str) -> None:
    assert f"{sub_str} has at least one failed job in submission tests" not in messages
    assert "Submissions to approve:" in messages
    assert "Submission approval process finished" in messages
    assert f"* {sub_str}" in messages


def assert_submission_not_approved(messages: list[str], sub_str: str, reason: str) -> None:
    assert reason in messages
    assert "Submissions to approve:" in messages
    assert "Submission approval process finished" in messages
    assert f"* {sub_str}" not in messages


def assert_log_messages(messages: list[str], expected_messages: list[str]) -> None:
    for msg in expected_messages:
        assert msg in messages


def fake_osc_get_config(override_apiurl: str) -> None:
    assert override_apiurl == settings.obs_url


def fake_get_request_list(url: str, project: str, **_kwargs: Any) -> list[osc.core.Request]:
    assert url == settings.obs_url
    assert "OBS:PROJECT" in project
    req = osc.core.Request()
    req.reqid = 42
    req.state = "review"
    req.reviews = [ReviewState("review", settings.obs_group)]
    req.actions = [
        Action(
            tgt_project="SUSE:Products:SLE-Product-SLES:16.0",
            src_project="SUSE:Products:SLE-Product-SLES:16.0:TEST",
            src_package="000productcompose:sles_aarch64",
        )
    ]
    return [req]


def fake_get_repos_of_project(url: str, prj: str) -> list[Repo]:
    assert url == settings.obs_url
    if prj == "SUSE:Products:SLE-Product-SLES:16.0:TEST":
        return [Repo("product", "local")]
    return [Repo("images", "local")]


def fake_get_binarylist(url: str, prj: str, repo: str, arch: str, package: str) -> list[str]:
    assert url == settings.obs_url
    assert package == "000productcompose:sles_aarch64"
    assert arch == "local"
    if prj == "SUSE:Products:SLE-Product-SLES:16.0:TEST" and repo == "product":
        return ["SLES-16.0-aarch64-Build160.4-Source.report", "foo"]
    return ["SLES-16.0-aarch64-Build160.4-Source.report", "bar"]


def fake_get_binary_file(
    url: str,
    prj: str,
    repo: str,
    arch: str,
    package: str,
    filename: str,
    target_filename: str,
) -> None:
    assert url == settings.obs_url
    assert package == "000productcompose:sles_aarch64"
    assert arch == "local"
    assert repo in {"images", "product"}
    assert filename == "SLES-16.0-aarch64-Build160.4-Source.report"
    Path(target_filename).symlink_to(Path(f"responses/source-report-{prj}.xml").absolute())


def fake_change_review_state(apiurl: str, reqid: str, newstate: str, by_group: str, message: str) -> None:
    assert apiurl == settings.obs_url
    assert reqid == "42"
    assert newstate == "accepted"
    assert by_group == settings.obs_group
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
    caplog.set_level(logging.DEBUG, logger="bot.requests")
    caplog.set_level(logging.DEBUG, logger="bot.loader.buildinfo")

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
    product_regex = "^SLES$"
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
    mock_post_job = MagicMock()
    mocker.patch("openqabot.openqa.OpenQAInterface.post_job", new=mock_post_job)
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


def make_passing_and_failing_job() -> dict:
    return {"done": {"passed": {"job_ids": [20]}, "failed": {"job_ids": [21]}}}


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
            responses.GET,
            openqa_url,
            json=json,
            match=[responses.matchers.query_param_matcher(merge_dicts(base_params, params))],
        )
        for (params, json) in list_of_params
    ]
