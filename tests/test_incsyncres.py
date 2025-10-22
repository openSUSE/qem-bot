from collections import namedtuple
import logging
from urllib.parse import urlparse
import pytest
import responses
import openqabot.incsyncres
from openqabot.incsyncres import IncResultsSync
from openqabot import QEM_DASHBOARD

namespace = namedtuple("Namespace", ["dry", "token", "openqa_instance"])


@pytest.fixture
def get_a_i(monkeypatch):
    def fake(*args):
        return [100]

    monkeypatch.setattr(openqabot.incsyncres, "get_active_incidents", fake)


@responses.activate
def test_clone_dry(get_a_i, caplog):
    caplog.set_level(logging.DEBUG)

    # get_incident_settings_data
    data = [
        {
            "id": 110,
            "flavor": "FakeFlavor",
            "arch": "arch",
            "settings": {"DISTRI": "linux", "BUILD": "123"},
            "version": "13.3",
        }
    ]

    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/incident_settings/100",
        json=data,
    )

    # get jobs
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
            }
        ]
    }
    responses.add(
        method="GET",
        url="http://instance.qa/api/v1/jobs?scope=relevant&flavor=FakeFlavor&distri=linux&build=123&version=13.3&arch=arch",
        json=data,
    )

    args = namespace(False, "ToKeN", urlparse("http://instance.qa"))

    syncer = IncResultsSync(args)

    ret = syncer()
    assert ret == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert [
        "No API key for instance.qa: only GET requests will be allowed",
        "Getting settings for 100",
        "Getting openQA tests results for Data(incident=100, settings_id=110, "
        "flavor='FakeFlavor', arch='arch', distri='linux', version='13.3', "
        "build='123', product='')",
        "Job '1234' already has a clone, ignoring",
        "End of bot run",
    ] == messages


@responses.activate
def test_nogroup_dry(get_a_i, caplog):
    caplog.set_level(logging.DEBUG)

    # get_incident_settings_data
    data = [
        {
            "id": 110,
            "flavor": "FakeFlavor",
            "arch": "arch",
            "settings": {"DISTRI": "linux", "BUILD": "123"},
            "version": "13.3",
        }
    ]

    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/incident_settings/100",
        json=data,
    )

    # get jobs
    data = {
        "jobs": [
            {
                "name": "FakeName",
                "id": 1234,
                "distri": "linux",
                "group_id": 10,
                "result": "passed",
                "clone_id": False,
            }
        ]
    }
    responses.add(
        method="GET",
        url="http://instance.qa/api/v1/jobs?scope=relevant&flavor=FakeFlavor&distri=linux&build=123&version=13.3&arch=arch",
        json=data,
    )

    args = namespace(False, "ToKeN", urlparse("http://instance.qa"))

    syncer = IncResultsSync(args)

    ret = syncer()
    assert ret == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert [
        "No API key for instance.qa: only GET requests will be allowed",
        "Getting settings for 100",
        "Getting openQA tests results for Data(incident=100, settings_id=110, "
        "flavor='FakeFlavor', arch='arch', distri='linux', version='13.3', "
        "build='123', product='')",
        "End of bot run",
    ] == messages


@responses.activate
def test_devel_fast_dry(get_a_i, caplog):
    caplog.set_level(logging.DEBUG)

    # get_incident_settings_data
    data = [
        {
            "id": 110,
            "flavor": "FakeFlavor",
            "arch": "arch",
            "settings": {"DISTRI": "linux", "BUILD": "123"},
            "version": "13.3",
        }
    ]

    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/incident_settings/100",
        json=data,
    )

    # get jobs
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
            }
        ]
    }
    responses.add(
        method="GET",
        url="http://instance.qa/api/v1/jobs?scope=relevant&flavor=FakeFlavor&distri=linux&build=123&version=13.3&arch=arch",
        json=data,
    )

    args = namespace(False, "ToKeN", urlparse("http://instance.qa"))

    syncer = IncResultsSync(args)

    ret = syncer()
    assert ret == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert [
        "No API key for instance.qa: only GET requests will be allowed",
        "Getting settings for 100",
        "Getting openQA tests results for Data(incident=100, settings_id=110, "
        "flavor='FakeFlavor', arch='arch', distri='linux', version='13.3', "
        "build='123', product='')",
        "Ignoring job '1234' in development group 'Devel FakeGroup'",
        "End of bot run",
    ] == messages


@responses.activate
def test_devel_dry(get_a_i, caplog):
    caplog.set_level(logging.DEBUG)

    # get_incident_settings_data
    data = [
        {
            "id": 110,
            "flavor": "FakeFlavor",
            "arch": "arch",
            "settings": {"DISTRI": "linux", "BUILD": "123"},
            "version": "13.3",
        }
    ]

    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/incident_settings/100",
        json=data,
    )

    # get jobs
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
            }
        ]
    }
    responses.add(
        method="GET",
        url="http://instance.qa/api/v1/jobs?scope=relevant&flavor=FakeFlavor&distri=linux&build=123&version=13.3&arch=arch",
        json=data,
    )

    # parent id
    data = [{"parent_id": 9}]
    responses.add(
        method="GET", url="http://instance.qa/api/v1/job_groups/10", json=data
    )

    args = namespace(False, "ToKeN", urlparse("http://instance.qa"))

    syncer = IncResultsSync(args)

    ret = syncer()
    assert ret == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert [
        "No API key for instance.qa: only GET requests will be allowed",
        "Getting settings for 100",
        "Getting openQA tests results for Data(incident=100, settings_id=110, "
        "flavor='FakeFlavor', arch='arch', distri='linux', version='13.3', "
        "build='123', product='')",
        "Ignoring job '1234' in development group 'FakeGroup'",
        "End of bot run",
    ] == messages


@responses.activate
def test_passed_dry(get_a_i, caplog):
    caplog.set_level(logging.DEBUG)

    # get_incident_settings_data
    data = [
        {
            "id": 110,
            "flavor": "FakeFlavor",
            "arch": "arch",
            "settings": {"DISTRI": "linux", "BUILD": "123"},
            "version": "13.3",
        }
    ]

    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/incident_settings/100",
        json=data,
    )

    # get jobs
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
            }
        ]
    }
    responses.add(
        method="GET",
        url="http://instance.qa/api/v1/jobs?scope=relevant&flavor=FakeFlavor&distri=linux&build=123&version=13.3&arch=arch",
        json=data,
    )

    # parent id
    data = [{"parent_id": 100}]
    responses.add(
        method="GET", url="http://instance.qa/api/v1/job_groups/10", json=data
    )

    args = namespace(False, "ToKeN", urlparse("http://instance.qa"))

    syncer = IncResultsSync(args)

    ret = syncer()
    assert ret == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert [
        "No API key for instance.qa: only GET requests will be allowed",
        "Getting settings for 100",
        "Getting openQA tests results for Data(incident=100, settings_id=110, "
        "flavor='FakeFlavor', arch='arch', distri='linux', version='13.3', "
        "build='123', product='')",
        "Posting results of incident job 1234 with status passed",
        "Full post data: {'arch': 'arch',\n"
        " 'build': '123',\n"
        " 'distri': 'linux',\n"
        " 'flavor': 'FakeFlavor',\n"
        " 'group_id': 10,\n"
        " 'incident_settings': 110,\n"
        " 'job_group': 'FakeGroup',\n"
        " 'job_id': 1234,\n"
        " 'name': 'FakeName',\n"
        " 'status': 'passed',\n"
        " 'update_settings': None,\n"
        " 'version': '13.3'}",
        "Dry run -- data in dashboard untouched",
        "End of bot run",
    ] == messages
