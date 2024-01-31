from copy import deepcopy
import logging

import pytest

from openqabot.errors import (
    NoRepoFoundError,
    EmptyPackagesError,
    EmptyChannels,
    NoResultsError,
)
from openqabot.types import Repos
from openqabot.types.incident import Incident
import openqabot.types.incident
from openqabot.utils import (
    retry3 as requests,
)  # only needed for the mocking see openSUSE/qem-bot/issues/161

test_data = {
    "approved": False,
    "channels": [
        "SUSE:Updates:openSUSE-SLE:15.4",
        "SUSE:Updates:SLE-Module-Development-Tools-OBS:15-SP4:aarch64",
        "SUSE:Updates:SLE-Module-Development-Tools-OBS:15-SP4:x86_64",
        "SUSE:SLE-15-SP4:Update",
        "SUSE:Updates:SLE-Module-Public-Cloud:15-SP4:x86_64",
        "SUSE:Updates:SLE-Module-Public-Cloud:15-SP4:aarch64",
    ],
    "emu": False,
    "inReview": True,
    "inReviewQAM": True,
    "isActive": True,
    "number": 24618,
    "packages": ["some", "package", "name"],
    "project": "SUSE:Maintenance:24618",
    "rr_number": 274060,
    "embargoed": True,
    "priority": 600,
}


@pytest.fixture
def mock_good(monkeypatch):
    def fake(*args, **kwargs):
        return 12345

    monkeypatch.setattr(openqabot.types.incident, "get_max_revision", fake)


@pytest.fixture
def mock_ex(monkeypatch):
    def fake(*args, **kwargs):
        raise NoRepoFoundError

    monkeypatch.setattr(openqabot.types.incident, "get_max_revision", fake)


def test_inc_normal(mock_good):
    inc = Incident(test_data)

    assert not inc.livepatch
    assert not inc.emu
    assert not inc.staging
    assert inc.embargoed
    assert str(inc) == "24618"
    assert repr(inc) == "<Incident: SUSE:Maintenance:24618:274060>"
    assert inc.id == 24618
    assert inc.rrid == "SUSE:Maintenance:24618:274060"
    assert inc.channels == [
        Repos(product="SLE-Module-Public-Cloud", version="15-SP4", arch="x86_64"),
        Repos(product="SLE-Module-Public-Cloud", version="15-SP4", arch="aarch64"),
        Repos(product="openSUSE-SLE", version="15.4", arch="x86_64"),
    ]
    assert inc.contains_package(["foo", "bar", "some"])
    assert not inc.contains_package(["foo", "bar"])


def test_inc_normal_livepatch(mock_good):
    modified_data = deepcopy(test_data)
    modified_data["packages"] = ["kernel-livepatch"]
    inc = Incident(modified_data)

    assert inc.livepatch


def test_inc_norepo(mock_ex):
    with pytest.raises(NoRepoFoundError):
        Incident(test_data)


def test_inc_nopackage(mock_good):
    bad_data = deepcopy(test_data)
    bad_data["packages"] = []
    with pytest.raises(EmptyPackagesError):
        Incident(bad_data)


def test_inc_nochannels(mock_good):
    bad_data = deepcopy(test_data)
    bad_data["channels"] = []
    with pytest.raises(EmptyChannels):
        Incident(bad_data)


def test_inc_nochannels2(mock_good):
    bad_data = deepcopy(test_data)
    bad_data["channels"] = [
        "SUSE:SLE-15-SP4:Update",
        "SUSE:Updates:SLE-Module-Development-Tools-OBS:15-SP4:x86_64",
        "SUSE:Updates:SLE-Module-SUSE-Manager-Server:15-SP4:aarch64",
    ]
    with pytest.raises(EmptyChannels):
        Incident(bad_data)


def test_inc_revisions(mock_good):
    incident = Incident(test_data)
    assert incident.revisions_with_fallback("x86_64", "15-SP4")
    assert incident.revisions_with_fallback("aarch64", "15-SP4")

    unversioned_data = deepcopy(test_data)
    unversioned_data["channels"] = [
        "SUSE:Updates:SLE-Module-HPC:12:x86_64",
    ]
    incident = Incident(unversioned_data)
    assert incident.revisions_with_fallback("x86_64", "12")
    assert incident.revisions_with_fallback("x86_64", "12-SP5")
    assert not incident.revisions_with_fallback("aarch64", "12")
    assert not incident.revisions_with_fallback("aarch64", "12-SP5")


class MockResponse:
    # TODO: collect all instances where the same pattern is used and refactor,
    # see openSUSE/qem-bot/issues/161
    def __init__(self, json_data):
        self.json_data = json_data

    def json(self):
        return self.json_data


def mock_get(url, headers):
    return MockResponse(
        json_data=[
            {"status": "passed", "job_id": 1},
            {"status": "failed", "job_id": 2},
            {"status": "passed", "job_id": 3},
        ]
    )


def test_inc_has_failures(caplog, mock_good, monkeypatch):

    monkeypatch.setattr(requests, "get", mock_get)
    caplog.set_level(logging.DEBUG)
    # Create an incident object
    inc = Incident(test_data)

    # Call the has_failures method
    has_failures = inc.has_failures("token")

    # Assert that the method returns True since there is a failed job
    assert has_failures

    assert caplog.records[0].message == "Found 1 failed jobs for incident 24618:"
    assert (
        caplog.records[1].message
        == "Job 2 is not marked as acceptable for incident 24618"
    )
    assert len(caplog.records) == 2

    caplog.set_level(logging.INFO)
    caplog.clear()

    inc.has_failures("token")

    # Check that the log only has one message, and that it matches our incident
    assert caplog.records[0].message == "Found 1 failed jobs for incident 24618:"
    assert len(caplog.records) == 1
