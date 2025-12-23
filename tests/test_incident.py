# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import logging
from collections.abc import Generator
from copy import deepcopy
from typing import Any, NoReturn

import pytest
from pytest_mock import MockerFixture

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
def mock_good(mocker: MockerFixture) -> Generator[None, None, None]:
    def fake(*_args: Any, **_kwargs: Any) -> int:
        return 12345

    return mocker.patch("openqabot.types.incident.get_max_revision", side_effect=fake)


@pytest.fixture
def mock_ex(mocker: MockerFixture) -> Generator[None, None, None]:
    def fake(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise NoRepoFoundError

    return mocker.patch("openqabot.types.incident.get_max_revision", side_effect=fake)


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


def test_inc_create(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    # Test EmptyChannelsError
    bad_data = deepcopy(test_data)
    bad_data["channels"] = []
    assert Incident.create(bad_data) is None
    assert "ignored: No channels found for project" in caplog.text

    # Test EmptyPackagesError
    caplog.clear()
    bad_data = deepcopy(test_data)
    bad_data["packages"] = []
    assert Incident.create(bad_data) is None
    assert "ignored: No packages found for project" in caplog.text


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


@pytest.mark.usefixtures("mock_good")
def test_inc_arch_filter() -> None:
    inc = Incident(test_data)
    inc.arch_filter = ["aarch64"]
    # x86_64 should be skipped in _rev
    inc.compute_revisions_for_product_repo(None, None)
    assert ArchVer("aarch64", "15-SP4") in inc.revisions
    assert ArchVer("x86_64", "15.4") not in inc.revisions


def test_inc_rev_multiple_repos(mocker: MockerFixture) -> None:
    data = deepcopy(test_data)
    data["channels"].append("SUSE:Updates:SLE-Module-Basesystem:15-SP4:x86_64")
    inc = Incident(data)
    mock_get_max = mocker.patch("openqabot.types.incident.get_max_revision", return_value=123)
    inc.compute_revisions_for_product_repo(None, None)
    # verify get_max_revision was called with both repos for x86_64
    args = mock_get_max.call_args_list[0][0]
    assert len(args[0]) == 2


def test_inc_rev_no_repo_found(mocker: MockerFixture) -> None:
    inc = Incident(test_data)
    mocker.patch("openqabot.types.incident.get_max_revision", return_value=0)
    with pytest.raises(NoRepoFoundError):
        inc.compute_revisions_for_product_repo(None, None)


def test_inc_repr_no_rrid() -> None:
    data = deepcopy(test_data)
    data["rr_number"] = None
    inc = Incident(data)
    assert repr(inc) == f"<Incident: {data['project']}>"


def test_inc_is_livepatch_false() -> None:
    data = deepcopy(test_data)
    data["packages"] = ["kernel-default", "kernel-livepatch"]
    inc = Incident(data)
    assert not inc.livepatch


def test_inc_rev_product_repo_list(mocker: MockerFixture) -> None:
    inc = Incident(test_data)
    mock_get_max = mocker.patch("openqabot.types.incident.get_max_revision", return_value=123)
    inc.compute_revisions_for_product_repo(["repo1", "repo2"], None)
    assert mock_get_max.call_args[0][3] == "repo2"


def test_inc_rev_non_matching_version(mocker: MockerFixture) -> None:
    data = deepcopy(test_data)
    data["channels"] = ["SUSE:Updates:Product:unknown:x86_64"]
    inc = Incident(data)
    mocker.patch("openqabot.types.incident.get_max_revision", return_value=123)
    inc.compute_revisions_for_product_repo(None, None)
    assert ArchVer("x86_64", "unknown") in inc.revisions
