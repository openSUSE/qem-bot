# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from collections.abc import Generator
from copy import deepcopy
from typing import Any, NoReturn
from unittest.mock import patch

import pytest

import openqabot.types.incident
from openqabot.errors import EmptyChannelsError, EmptyPackagesError, NoRepoFoundError
from openqabot.types import ArchVer, Repos
from openqabot.types.incident import Incident

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
def mock_good() -> Generator[None, None, None]:
    def fake(*_args: Any, **_kwargs: Any) -> int:
        return 12345

    with patch("openqabot.types.incident.get_max_revision", side_effect=fake):
        yield


@pytest.fixture
def mock_ex(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise NoRepoFoundError

    monkeypatch.setattr(openqabot.types.incident, "get_max_revision", fake)


@pytest.mark.usefixtures("mock_good")
def test_inc_normal() -> None:
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


@pytest.mark.usefixtures("mock_good")
def test_inc_normal_livepatch() -> None:
    modified_data = deepcopy(test_data)
    modified_data["packages"] = ["kernel-livepatch"]
    inc = Incident(modified_data)

    assert inc.livepatch


@pytest.mark.usefixtures("mock_ex")
def test_inc_norepo() -> None:
    inc = Incident(test_data)
    with pytest.raises(NoRepoFoundError):
        inc.revisions_with_fallback("x86_64", "15-SP4")


@pytest.mark.usefixtures("mock_good")
def test_inc_nopackage() -> None:
    bad_data = deepcopy(test_data)
    bad_data["packages"] = []
    with pytest.raises(EmptyPackagesError):
        Incident(bad_data)


@pytest.mark.usefixtures("mock_good")
def test_inc_nochannels() -> None:
    bad_data = deepcopy(test_data)
    bad_data["channels"] = []
    with pytest.raises(EmptyChannelsError):
        Incident(bad_data)


@pytest.mark.usefixtures("mock_good")
def test_inc_nochannels2() -> None:
    bad_data = deepcopy(test_data)
    bad_data["channels"] = [
        "SUSE:SLE-15-SP4:Update",
        "SUSE:Updates:SLE-Module-Development-Tools-OBS:15-SP4:x86_64",
        "SUSE:Updates:SLE-Module-SUSE-Manager-Server:15-SP4:aarch64",
    ]
    with pytest.raises(EmptyChannelsError):
        Incident(bad_data)


@pytest.mark.usefixtures("mock_good")
def test_inc_revisions() -> None:
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


@pytest.mark.usefixtures("mock_good")
def test_slfo_channels_and_revisions() -> None:
    slfo_data = deepcopy(test_data)
    slfo_data["project"] = "SUSE:SLFO"
    slfo_data["channels"] = [
        "SUSE:SLFO:1.1.99:PullRequest:166:SLES:x86_64#15.99",
        "SUSE:SLFO:1.1.99:PullRequest:166:SLES:aarch64#15.99",
    ]
    expected_channels = [
        Repos("SUSE:SLFO", "1.1.99:PullRequest:166:SLES", "x86_64", "15.99"),
        Repos("SUSE:SLFO", "1.1.99:PullRequest:166:SLES", "aarch64", "15.99"),
    ]
    expected_revisions = {
        ArchVer("aarch64", "15.99"): 12345,
        ArchVer("x86_64", "15.99"): 12345,
    }
    incident = Incident(slfo_data)
    incident.compute_revisions_for_product_repo(None, None)
    assert incident.channels == expected_channels
    assert incident.revisions == expected_revisions
