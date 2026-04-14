# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test SubResultsSync."""

import logging
from argparse import Namespace
from collections.abc import Generator

import pytest
import responses
from pytest_mock import MockerFixture

from openqabot.config import QEM_DASHBOARD
from openqabot.subsyncres import SubResultsSync

openqa_url = (
    "http://instance.qa/api/v1/jobs?scope=relevant&latest=1&flavor=FakeFlavor&distri=linux&build=123"
    "&version=13.3&arch=arch"
)


@pytest.fixture
def get_a_s(mocker: MockerFixture) -> Generator[None, None, None]:
    return mocker.patch("openqabot.subsyncres.get_active_submissions", return_value=[100])


@pytest.fixture
def mock_dashboard_settings() -> None:
    data = [
        {
            "id": 110,
            "flavor": "FakeFlavor",
            "arch": "arch",
            "settings": {"DISTRI": "linux", "BUILD": "123"},
            "version": "13.3",
        },
    ]
    responses.add(method="GET", url=f"{QEM_DASHBOARD}api/incident_settings/100", json=data)


@pytest.fixture
def args() -> Namespace:
    return Namespace(dry=False, token="ToKeN")


def prepare_syncer(caplog: pytest.LogCaptureFixture, args: Namespace) -> SubResultsSync:
    caplog.set_level(logging.INFO)
    return SubResultsSync(args)


@responses.activate
@pytest.mark.usefixtures("get_a_s", "mock_dashboard_settings")
def test_clone_dry(caplog: pytest.LogCaptureFixture, args: Namespace) -> None:
    data = {
        "jobs": [
            {
                "name": "FakeName",
                "id": 1234,
                "distri": "linux",
                "group_id": 10,
                "group": "Devel FakeGroup",
                "result": "passed",
                "clone_id": 1234,
            },
        ],
    }
    responses.add(method="GET", url=openqa_url, json=data)

    syncer = prepare_syncer(caplog, args)

    ret = syncer()
    assert ret == 0
    assert caplog.messages == [
        "Synchronizing results for 1 active submissions...",
        "Fetched 1 total jobs from openQA.",
        "Submission results sync completed: Synced 0 job results to the dashboard",
    ]


@responses.activate
@pytest.mark.usefixtures("get_a_s", "mock_dashboard_settings")
def test_nogroup_dry(caplog: pytest.LogCaptureFixture, args: Namespace) -> None:
    data = {
        "jobs": [
            {
                "name": "FakeName",
                "id": 1234,
                "distri": "linux",
                "group_id": 10,
                "result": "passed",
                "clone_id": False,
            },
        ],
    }
    responses.add(method="GET", url=openqa_url, json=data)

    syncer = prepare_syncer(caplog, args)

    ret = syncer()
    assert ret == 0
    assert caplog.messages == [
        "Synchronizing results for 1 active submissions...",
        "Fetched 1 total jobs from openQA.",
        "Submission results sync completed: Synced 0 job results to the dashboard",
    ]


@responses.activate
@pytest.mark.usefixtures("get_a_s", "mock_dashboard_settings")
def test_devel_fast_dry(caplog: pytest.LogCaptureFixture, args: Namespace) -> None:
    data = {
        "jobs": [
            {
                "name": "FakeName",
                "id": 1234,
                "distri": "linux",
                "group_id": 10,
                "group": "Devel FakeGroup",
                "result": "passed",
                "clone_id": False,
            },
        ],
    }
    responses.add(
        method="GET",
        url=openqa_url,
        json=data,
    )

    syncer = prepare_syncer(caplog, args)

    ret = syncer()
    assert ret == 0
    assert caplog.messages == [
        "Synchronizing results for 1 active submissions...",
        "Fetched 1 total jobs from openQA.",
        "Submission results sync completed: Synced 0 job results to the dashboard",
    ]


@responses.activate
@pytest.mark.usefixtures("get_a_s", "mock_dashboard_settings")
def test_devel_dry(caplog: pytest.LogCaptureFixture, args: Namespace) -> None:
    data = {
        "jobs": [
            {
                "name": "FakeName",
                "id": 1234,
                "distri": "linux",
                "group_id": 10,
                "group": "FakeGroup",
                "result": "passed",
                "clone_id": False,
            },
        ],
    }
    responses.add(method="GET", url=openqa_url, json=data)
    data = [{"parent_id": 9}]
    responses.add(method="GET", url="http://instance.qa/api/v1/job_groups/10", json=data)

    syncer = prepare_syncer(caplog, args)

    ret = syncer()
    assert ret == 0
    assert caplog.messages == [
        "Synchronizing results for 1 active submissions...",
        "Fetched 1 total jobs from openQA.",
        "Submission results sync completed: Synced 0 job results to the dashboard",
    ]


@responses.activate
@pytest.mark.usefixtures("get_a_s", "mock_dashboard_settings")
def test_passed_dry(caplog: pytest.LogCaptureFixture, args: Namespace) -> None:
    data = {
        "jobs": [
            {
                "name": "FakeName",
                "id": 1234,
                "distri": "linux",
                "group_id": 10,
                "group": "FakeGroup",
                "result": "passed",
                "clone_id": False,
            },
        ],
    }
    responses.add(method="GET", url=openqa_url, json=data)
    data = [{"parent_id": 100}]
    responses.add(method="GET", url="http://instance.qa/api/v1/job_groups/10", json=data)

    syncer = prepare_syncer(caplog, args)

    ret = syncer()
    assert ret == 0
    assert caplog.messages == [
        "Synchronizing results for 1 active submissions...",
        "Fetched 1 total jobs from openQA.",
        "openQA client not configured - skipping dashboard update",
        "Submission results sync completed: Synced 1 job results to the dashboard",
    ]
