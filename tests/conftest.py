# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Pytest configuration and fixtures."""

from __future__ import annotations

import os
import re
from argparse import Namespace
from collections import defaultdict
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

import openqabot.config as config_module
import responses
from openqabot.approver import Approver
from openqabot.config import Settings, settings
from openqabot.dashboard import clear_cache
from openqabot.errors import NoResultsError
from openqabot.loader.gitea import read_json_file
from openqabot.loader.qem import JobAggr
from openqabot.openqa import OpenQAInterface
from openqabot.repodiff import Package
from openqabot.requests import find_request_on_obs, get_obs_request_list

from .helpers import (
    add_two_passed_response,
    f_sub_approver,
    fake_change_review_state,
    fake_get_request_list,
    fake_openqa_responses_with_param_matching,
    fake_osc_get_config,
    make_passing_and_failing_job,
    obs_product_table_url,
    openqa_instance_url,
    openqa_url,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def fake_responses_for_unblocking_submissions_via_openqa_comments(
    request: pytest.FixtureRequest,
) -> None:
    params = request.param
    submission = params["submission"]
    responses.add(
        responses.GET,
        f"{settings.qem_dashboard_url}api/jobs/update/20005",
        json=[
            {"job_id": 100000, "status": "passed"},
            {"job_id": 100002, "status": "failed"},
            {"job_id": 100003, "status": "failed"},
            {"job_id": 100004, "status": "failed"},
        ],
    )
    add_two_passed_response()
    for job_id in params.get("not_acceptable_job_ids", []):
        responses.get(
            url=f"http://instance.qa/api/v1/jobs/{job_id}/comments",
            json=[{"text": ""}],
        )
    for job_id in params.get("acceptable_job_ids", [100002, 100003, 100004]):
        responses.get(
            url=f"http://instance.qa/api/v1/jobs/{job_id}/comments",
            json=[{"text": f"@review:acceptable_for:submission_{submission}:foo"}],
        )


def with_fake_qem(mode: str) -> Any:
    def decorator(test_func: object) -> object:
        test_func = pytest.mark.qem_behavior(mode)(test_func)
        return pytest.mark.usefixtures("fake_qem")(test_func)

    return decorator


@pytest.fixture
def fake_openqa_older_jobs_api() -> None:
    responses.get(
        re.compile(r"http://instance.qa/tests/.*/ajax\?previous_limit=.*&next_limit=0"),
        json={"data": []},
    )


@pytest.fixture
def fake_openqa_comment_api() -> None:
    responses.add(
        responses.GET,
        re.compile(r"http://instance.qa/api/v1/jobs/.*/comments"),
        json={"error": "job not found"},
        status=404,
    )


def make_approver(submission: int = 0, *, mocker: MockerFixture | None = None, comment: bool = False) -> int:
    if mocker:
        mocker.patch("openqabot.approver.Commenter", autospec=True)
    args = Namespace(
        dry=True,
        token="123",
        all_submissions=False,
        openqa_instance=openqa_instance_url,
        incident=submission,
        gitea_token=None,
        comment=comment,
    )
    instance = Approver(args)
    instance.client.retries = 0
    return instance()


@pytest.fixture(autouse=True)
def _auto_clear_cache() -> None:
    clear_cache()


@pytest.fixture(scope="session")
def _session_settings() -> dict[str, Any]:
    """Capture default settings once per session to speed up test reset."""
    with patch.dict(os.environ, {}, clear=True), patch("osc.conf.get_config", side_effect=RuntimeError):
        defaults = Settings()
        return {key: getattr(defaults, key) for key in Settings.model_fields}


@pytest.fixture(autouse=True)
def _reset_settings(mocker: MockerFixture, _session_settings: dict[str, Any]) -> None:
    # Maintain consistent environment and reset singleton settings for every test
    mocker.patch.dict(os.environ, {"OBS_URL": _session_settings["obs_url"]})
    for key, value in _session_settings.items():
        setattr(config_module.settings, key, value)


@pytest.fixture(autouse=True)
def _mock_load_dotenv(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.main.load_dotenv")


@pytest.fixture
def fake_qem(request: pytest.FixtureRequest, mocker: MockerFixture) -> None:
    request_param = request.node.get_closest_marker("qem_behavior").args[0]

    def f_sub_settins(sub: int, _token: str, submission_type: str | None = None, **_kwargs: Any) -> list[JobAggr]:  # noqa: ARG001
        if "inc" in request_param:
            msg = "No results for settings"
            raise NoResultsError(msg)
        results = {
            1: [JobAggr(i, aggregate=False, with_aggregate=True) for i in range(1000, 1010)],
            2: [JobAggr(i, aggregate=False, with_aggregate=True) for i in range(2000, 2010)],
            3: [
                JobAggr(3000, aggregate=False, with_aggregate=False),
                JobAggr(3001, aggregate=False, with_aggregate=False),
                JobAggr(3002, aggregate=False, with_aggregate=True),
                JobAggr(3002, aggregate=False, with_aggregate=False),
                JobAggr(3003, aggregate=False, with_aggregate=True),
            ],
            4: [JobAggr(i, aggregate=False, with_aggregate=False) for i in range(4000, 4010)],
            5: [JobAggr(i, aggregate=False, with_aggregate=False) for i in range(5000, 5010)],
        }
        return results.get(sub, [])

    def f_aggr_settings(sub: int, _token: str, submission_type: str | None = None) -> list[JobAggr]:  # noqa: ARG001
        if "aggr" in request_param:
            msg = "No results for settings"
            raise NoResultsError(msg)
        results = {
            5: [],
            4: [],
            1: [JobAggr(i, aggregate=True, with_aggregate=False) for i in range(10000, 10010)],
            2: [JobAggr(i, aggregate=True, with_aggregate=False) for i in range(20000, 20010)],
            3: [JobAggr(i, aggregate=True, with_aggregate=False) for i in range(30000, 30010)],
        }
        return results.get(sub, [])

    mocker.patch(
        "openqabot.approver.get_single_submission",
        side_effect=lambda _token, i, **_kwargs: [s for s in f_sub_approver() if s.sub == i],
    )
    mocker.patch("openqabot.approver.get_submissions_approver", side_effect=f_sub_approver)
    mocker.patch("openqabot.approver.get_submission_settings", side_effect=f_sub_settins)
    mocker.patch("openqabot.approver.get_aggregate_settings", side_effect=f_aggr_settings)

    OpenQAInterface.get_job_comments.cache_clear()
    OpenQAInterface.get_single_job.cache_clear()
    OpenQAInterface.get_older_jobs.cache_clear()
    OpenQAInterface.is_devel_group.cache_clear()

    Approver.is_job_marked_acceptable_for_submission.cache_clear()
    Approver.validate_job_qam.cache_clear()
    Approver.was_ok_before.cache_clear()
    Approver.get_jobs.cache_clear()


@pytest.fixture
def fake_two_passed_jobs() -> None:
    add_two_passed_response()


@pytest.fixture
def fake_no_jobs() -> None:
    responses.add(responses.GET, re.compile(f"{openqa_url}.*"), json={})


@pytest.fixture
def fake_no_jobs_with_param_matching() -> list[responses.BaseResponse]:
    return fake_openqa_responses_with_param_matching({})


@pytest.fixture
def fake_only_jobs_of_additional_builds_with_param_matching() -> list[responses.BaseResponse]:
    return fake_openqa_responses_with_param_matching(make_passing_and_failing_job())


@pytest.fixture
def fake_pending_jobs() -> None:
    responses.add(responses.GET, re.compile(f"{openqa_url}.*"), json={"scheduled": {}, "running": {}})


@pytest.fixture
def fake_not_ok_jobs() -> None:
    responses.add(responses.GET, re.compile(f"{openqa_url}.*"), json=make_passing_and_failing_job())


@pytest.fixture
def fake_ok_jobs() -> None:
    responses.add(
        responses.GET,
        re.compile(f"{openqa_url}.*"),
        json={"done": {"passed": {"job_ids": [22]}, "softfailed": {"job_ids": [24]}}},
    )


@pytest.fixture
def fake_product_repo() -> None:
    responses.add(responses.GET, obs_product_table_url, json=read_json_file("test-product-repo"))


@pytest.fixture
def fakeget_package_diff(mocker: MockerFixture) -> None:
    package_diff = defaultdict(set)
    package_diff["x86_64"] = {Package("foo", "1", "2", "3", "x86_64")}
    mocker.patch("openqabot.incrementapprover.IncrementApprover.get_package_diff", return_value=package_diff)


@pytest.fixture(autouse=True)
def mock_osc(mocker: MockerFixture) -> None:
    # Clear caches to ensure isolation between tests

    find_request_on_obs.cache_clear()  # type: ignore[attr-defined]
    get_obs_request_list.cache_clear()

    mocker.patch("osc.core.get_request_list", side_effect=fake_get_request_list)
    mocker.patch("osc.core.change_review_state", side_effect=fake_change_review_state)
    mocker.patch("osc.conf.get_config", side_effect=fake_osc_get_config)
