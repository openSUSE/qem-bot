# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import logging
from collections.abc import Generator
from copy import deepcopy
from typing import Any, NoReturn, cast

import pytest
from pytest_mock import MockerFixture

from openqabot.errors import EmptyChannelsError, EmptyPackagesError, NoRepoFoundError
from openqabot.types.submission import Submission
from openqabot.types.types import ArchVer, Repos

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

    return mocker.patch("openqabot.types.submission.get_max_revision", side_effect=fake)


@pytest.fixture
def mock_ex(mocker: MockerFixture) -> Generator[None, None, None]:
    def fake(*_args: Any, **_kwargs: Any) -> NoReturn:
        raise NoRepoFoundError

    return mocker.patch("openqabot.types.submission.get_max_revision", side_effect=fake)


@pytest.mark.usefixtures("mock_good")
def test_sub_normal() -> None:
    sub = Submission(test_data)

    assert not sub.livepatch
    assert not sub.emu
    assert not sub.staging
    assert sub.embargoed
    assert str(sub) == "smelt:24618"
    assert repr(sub) == "<Submission: smelt:SUSE:Maintenance:24618:274060>"
    assert sub.id == 24618
    assert sub.rrid == "SUSE:Maintenance:24618:274060"
    assert sub.channels == [
        Repos(product="SLE-Module-Public-Cloud", version="15-SP4", arch="x86_64"),
        Repos(product="SLE-Module-Public-Cloud", version="15-SP4", arch="aarch64"),
        Repos(product="openSUSE-SLE", version="15.4", arch="x86_64"),
    ]
    assert sub.contains_package(["foo", "bar", "some"])
    assert not sub.contains_package(["foo", "bar"])


@pytest.mark.usefixtures("mock_good")
def test_sub_normal_livepatch() -> None:
    modified_data = deepcopy(test_data)
    modified_data["packages"] = ["kernel-livepatch"]
    sub = Submission(modified_data)

    assert sub.livepatch


@pytest.mark.usefixtures("mock_ex")
def test_sub_norepo() -> None:
    sub = Submission(test_data)
    assert sub.revisions_with_fallback("x86_64", "15-SP4") is None


@pytest.mark.usefixtures("mock_good")
def test_sub_nopackage() -> None:
    bad_data = deepcopy(test_data)
    bad_data["packages"] = []
    with pytest.raises(EmptyPackagesError):
        Submission(bad_data)


@pytest.mark.usefixtures("mock_good")
def test_sub_nochannels() -> None:
    bad_data = deepcopy(test_data)
    bad_data["channels"] = []
    with pytest.raises(EmptyChannelsError):
        Submission(bad_data)


@pytest.mark.usefixtures("mock_good")
def test_sub_nochannels2() -> None:
    bad_data = deepcopy(test_data)
    bad_data["channels"] = [
        "SUSE:SLE-15-SP4:Update",
        "SUSE:Updates:SLE-Module-Development-Tools-OBS:15-SP4:x86_64",
        "SUSE:Updates:SLE-Module-SUSE-Manager-Server:15-SP4:aarch64",
    ]
    with pytest.raises(EmptyChannelsError):
        Submission(bad_data)


def test_sub_create(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    # Test EmptyChannelsError
    bad_data = deepcopy(test_data)
    bad_data["channels"] = []
    assert Submission.create(bad_data) is None
    assert "ignored: No channels found for project" in caplog.text

    # Test EmptyPackagesError
    caplog.clear()
    bad_data = deepcopy(test_data)
    bad_data["packages"] = []
    assert Submission.create(bad_data) is None
    assert "ignored: No packages found for project" in caplog.text


@pytest.mark.usefixtures("mock_good")
def test_sub_revisions() -> None:
    submission = Submission(test_data)
    assert submission.revisions_with_fallback("x86_64", "15-SP4")
    assert submission.revisions_with_fallback("aarch64", "15-SP4")

    unversioned_data = deepcopy(test_data)
    unversioned_data["channels"] = [
        "SUSE:Updates:SLE-Module-HPC:12:x86_64",
    ]
    submission = Submission(unversioned_data)
    assert submission.revisions_with_fallback("x86_64", "12")
    assert submission.revisions_with_fallback("x86_64", "12-SP5")
    assert not submission.revisions_with_fallback("aarch64", "12")
    assert not submission.revisions_with_fallback("aarch64", "12-SP5")


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
    submission = Submission(slfo_data)
    submission.compute_revisions_for_product_repo(None, None)
    assert submission.channels == expected_channels
    assert submission.revisions == expected_revisions


def test_sub_rev_multiple_repos(mocker: MockerFixture) -> None:
    data: Any = deepcopy(test_data)
    cast("Any", data["channels"]).append("SUSE:Updates:SLE-Module-Basesystem:15-SP4:x86_64")
    sub = Submission(data)
    mock_get_max = mocker.patch("openqabot.types.submission.get_max_revision", return_value=123)
    sub.compute_revisions_for_product_repo(None, None)
    # verify get_max_revision was called with both repos for x86_64
    args = mock_get_max.call_args_list[0][0]
    assert len(args[0]) == 2


def test_sub_rev_no_repo_found(mocker: MockerFixture) -> None:
    sub = Submission(test_data)
    mocker.patch("openqabot.types.submission.get_max_revision", return_value=0)
    assert not sub.compute_revisions_for_product_repo(None, None)


def test_sub_repr_no_rrid() -> None:
    data = deepcopy(test_data)
    data["rr_number"] = None
    sub = Submission(data)
    assert repr(sub) == f"<Submission: smelt:{data['project']}>"


def test_sub_is_livepatch_false() -> None:
    data = deepcopy(test_data)
    data["packages"] = ["kernel-default", "kernel-livepatch"]
    sub = Submission(data)
    assert not sub.livepatch


def test_sub_rev_product_repo_list(mocker: MockerFixture) -> None:
    sub = Submission(test_data)
    mock_get_max = mocker.patch("openqabot.types.submission.get_max_revision", return_value=123)
    sub.compute_revisions_for_product_repo(["repo1", "repo2"], None)
    # options is the 4th positional argument (index 3)
    assert mock_get_max.call_args[0][3].product_name == "repo2"


def test_sub_rev_non_matching_version(mocker: MockerFixture) -> None:
    data = deepcopy(test_data)
    data["channels"] = ["SUSE:Updates:Product:unknown:x86_64"]
    sub = Submission(data)
    mocker.patch("openqabot.types.submission.get_max_revision", return_value=123)
    sub.compute_revisions_for_product_repo(None, None)
    assert sub.revisions is not None
    assert ArchVer("x86_64", "unknown") in sub.revisions


def test_sub_rev_empty_channels() -> None:
    from unittest.mock import MagicMock

    sub = MagicMock(spec=Submission)
    sub.id = 123
    sub.channels = []
    sub._rev_cache_params = None  # noqa: SLF001
    sub._rev_logged = False  # noqa: SLF001
    sub.project = "project"
    sub.compute_revisions_for_product_repo = Submission.compute_revisions_for_product_repo.__get__(sub, Submission)
    sub._rev = Submission._rev  # noqa: SLF001
    assert not sub.compute_revisions_for_product_repo(None, None)


def test_revisions_with_fallback_no_revisions(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    sub = Submission(test_data)
    mocker.patch.object(sub, "compute_revisions_for_product_repo")
    caplog.set_level(logging.DEBUG, logger="bot.types.submission")
    assert sub.revisions_with_fallback("x86_64", "15-SP4") is None
    assert "Submission smelt:24618: No revisions available" in caplog.text


def test_slfo_channels_edge_cases(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.INFO)
    slfo_data = deepcopy(test_data)
    slfo_data["channels"] = [
        "SUSE:SLFO:1.1.99:PullRequest:166:SLES:x86_64#15.99",  # normal
        "SUSE:SLFO:too_short",  # too short, line 58
        "SUSE:SLFO:1.1.99:PullRequest:166:UNKNOWN:x86_64#15.99",  # unknown product, line 64
    ]

    def mock_product_name(p: str) -> str:
        return "SLES" if "SLES" in p else "UNKNOWN"

    mocker.patch("openqabot.loader.gitea.get_product_name", side_effect=mock_product_name)
    mocker.patch("openqabot.types.submission.OBS_PRODUCTS", ["SLES"])

    submission = Submission(slfo_data)
    submission.log_skipped()

    assert "Submission smelt:24618: Product UNKNOWN is not in considered products" in caplog.text

    assert len(submission.channels) == 1  # only the first one
    assert submission.channels[0].product == "SUSE:SLFO"

    caplog.clear()
    mocker.patch("openqabot.types.submission.OBS_PRODUCTS", ["all"])
    submission = Submission(slfo_data)
    submission.log_skipped()
    assert "Product UNKNOWN is not in considered products" not in caplog.text
    assert len(submission.channels) == 2  # SLES and UNKNOWN

    caplog.clear()
    mocker.patch("openqabot.types.submission.OBS_PRODUCTS", [""])
    # Need a channel with no product name
    slfo_data_no_prod = deepcopy(test_data)
    slfo_data_no_prod["channels"] = ["SUSE:SLFO:1.1.99:PullRequest:166:x86_64#15.99"]
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="")
    submission = Submission(slfo_data_no_prod)
    assert len(submission.channels) == 1
    assert submission.channels[0].product == "SUSE:SLFO"


def test_compute_revisions_cache_hit(mocker: MockerFixture) -> None:
    submission = Submission(test_data)
    submission._rev_cache_params = (None, None, None)  # noqa: SLF001
    submission.revisions = {"some": "data"}  # type: ignore[assignment]
    # Should return True without calling _rev
    mock_rev = mocker.patch.object(submission, "_rev")
    assert submission.compute_revisions_for_product_repo(None, None)
    mock_rev.assert_not_called()


def test_compute_revisions_cache_hit_none(mocker: MockerFixture) -> None:
    submission = Submission(test_data)
    submission._rev_cache_params = (None, None, None)  # noqa: SLF001
    submission.revisions = None
    # Should return False without calling _rev
    mock_rev = mocker.patch.object(submission, "_rev")
    assert not submission.compute_revisions_for_product_repo(None, None)
    mock_rev.assert_not_called()


def test_submission_create_empty_packages(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    data = deepcopy(test_data)
    data["packages"] = []  # This triggers EmptyPackagesError

    sub = Submission.create(data)
    assert sub is None
    assert "Submission smelt:24618 ignored: No packages found for project" in caplog.text


def test_compute_revisions_logging_once(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    data = deepcopy(test_data)

    sub = Submission(data)
    # Mock _rev to raise NoRepoFoundError
    mocker.patch.object(sub, "_rev", side_effect=NoRepoFoundError("test error"))

    # First call should log
    assert not sub.compute_revisions_for_product_repo(None, None)
    assert "RepoHash calculation failed for project SUSE:Maintenance:24618: test error" in caplog.text
    caplog.clear()

    # Second call with same params (cache hit)
    assert not sub.compute_revisions_for_product_repo(None, None)
    assert "RepoHash calculation failed" not in caplog.text

    # Third call with different params (bypass cache, but already logged)
    assert not sub.compute_revisions_for_product_repo("different", "params")
    assert "RepoHash calculation failed" not in caplog.text


def test_sub_rev_limit_archs(mocker: MockerFixture) -> None:
    data = deepcopy(test_data)
    data["channels"] = [
        "SUSE:Updates:SLE-Module-Public-Cloud:15-SP4:x86_64",
        "SUSE:Updates:SLE-Module-Public-Cloud:15-SP4:aarch64",
    ]
    sub = Submission(data)
    mock_get_max = mocker.patch("openqabot.types.submission.get_max_revision", return_value=123)
    # limit_archs only includes x86_64, aarch64 should be skipped
    sub.compute_revisions_for_product_repo(None, None, limit_archs={"x86_64"})
    # verify get_max_revision was called only once (for x86_64)
    assert mock_get_max.call_count == 1
    assert mock_get_max.call_args[0][1] == "x86_64"


def test_log_skipped_twice(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    data = deepcopy(test_data)
    sub = Submission(data)
    sub.skipped_products.add("UNKNOWN")

    sub.log_skipped()
    assert "Product UNKNOWN is not in considered products" in caplog.text
    caplog.clear()

    # Second call should return early
    sub.log_skipped()
    assert "Product UNKNOWN is not in considered products" not in caplog.text
