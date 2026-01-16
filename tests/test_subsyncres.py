# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# ruff: noqa: S106 "Possible hardcoded password assigned to argument"

import logging
from argparse import Namespace
from collections.abc import Generator
from urllib.parse import urlparse

import pytest
from pytest_mock import MockerFixture

import responses
from openqabot.config import QEM_DASHBOARD
from openqabot.subsyncres import SubResultsSync

openqa_url = "http://instance.qa/api/v1/jobs?scope=relevant&latest=1&flavor=FakeFlavor&distri=linux&build=123&version=13.3&arch=arch"


@pytest.fixture
def get_a_s(mocker: MockerFixture) -> Generator[None, None, None]:
    return mocker.patch("openqabot.subsyncres.get_active_submissions", return_value=[100])


@responses.activate
@pytest.mark.usefixtures("get_a_s")
def test_clone_dry(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
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
    args = Namespace(dry=False, token="ToKeN", openqa_instance=urlparse("http://instance.qa"))

    syncer = SubResultsSync(args)

    ret = syncer()
    assert ret == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert messages == [
        "Fetching settings for submission 100",
        (
            "Fetching openQA jobs for Data(submission=100, settings_id=110, "
            "flavor='FakeFlavor', arch='arch', distri='linux', version='13.3', "
            "build='123', product='')"
        ),
        "Submission results sync completed",
    ]


@responses.activate
@pytest.mark.usefixtures("get_a_s")
def test_nogroup_dry(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
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
    args = Namespace(dry=False, token="ToKeN", openqa_instance=urlparse("http://instance.qa"))

    syncer = SubResultsSync(args)

    ret = syncer()
    assert ret == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert messages == [
        "Fetching settings for submission 100",
        (
            "Fetching openQA jobs for Data(submission=100, settings_id=110, "
            "flavor='FakeFlavor', arch='arch', distri='linux', version='13.3', "
            "build='123', product='')"
        ),
        "Submission results sync completed",
    ]


@responses.activate
@pytest.mark.usefixtures("get_a_s")
def test_devel_fast_dry(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    data = [
        {
            "id": 110,
            "flavor": "FakeFlavor",
            "arch": "arch",
            "settings": {"DISTRI": "linux", "BUILD": "123"},
            "version": "13.3",
        },
    ]

    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/incident_settings/100",
        json=data,
    )
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
    args = Namespace(dry=False, token="ToKeN", openqa_instance=urlparse("http://instance.qa"))

    syncer = SubResultsSync(args)

    ret = syncer()
    assert ret == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert messages == [
        "Fetching settings for submission 100",
        (
            "Fetching openQA jobs for Data(submission=100, settings_id=110, "
            "flavor='FakeFlavor', arch='arch', distri='linux', version='13.3', "
            "build='123', product='')"
        ),
        "Submission results sync completed",
    ]


@responses.activate
@pytest.mark.usefixtures("get_a_s")
def test_devel_dry(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
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
    args = Namespace(dry=False, token="ToKeN", openqa_instance=urlparse("http://instance.qa"))

    syncer = SubResultsSync(args)

    ret = syncer()
    assert ret == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert messages == [
        "Fetching settings for submission 100",
        (
            "Fetching openQA jobs for Data(submission=100, settings_id=110, "
            "flavor='FakeFlavor', arch='arch', distri='linux', version='13.3', "
            "build='123', product='')"
        ),
        "Submission results sync completed",
    ]


@responses.activate
@pytest.mark.usefixtures("get_a_s")
def test_passed_dry(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
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
    args = Namespace(dry=False, token="ToKeN", openqa_instance=urlparse("http://instance.qa"))

    syncer = SubResultsSync(args)

    ret = syncer()
    assert ret == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert messages == [
        "Fetching settings for submission 100",
        (
            "Fetching openQA jobs for Data(submission=100, settings_id=110, "
            "flavor='FakeFlavor', arch='arch', distri='linux', version='13.3', "
            "build='123', product='')"
        ),
        "Syncing submission job 1234: Status passed",
        "Dry run: Skipping dashboard update",
        "Submission results sync completed",
    ]
