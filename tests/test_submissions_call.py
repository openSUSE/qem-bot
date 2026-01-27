# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Generator

import pytest
from pytest_mock import MockerFixture

from openqabot.types.baseconf import JobConfig
from openqabot.types.submissions import Submissions
from openqabot.types.types import ArchVer, Repos

from .fixtures.submissions import MockSubmission


def test_submissions_call() -> None:
    """Test for the bare minimal set of arguments needed by the callable."""
    test_config = {}
    test_config["FLAVOR"] = {}
    sub = Submissions(
        JobConfig(
            product="",
            product_repo=None,
            product_version=None,
            settings={},
            config=test_config,
        ),
        extrasettings=set(),
    )
    res = sub(submissions=[], token={}, ci_url="", ignore_onetime=False)
    assert res == []


def test_submissions_call_with_flavors() -> None:
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": []}}
    sub = Submissions(
        JobConfig(
            product="",
            product_repo=None,
            product_version=None,
            settings={},
            config=test_config,
        ),
        extrasettings=set(),
    )
    res = sub(submissions=[], token={}, ci_url="", ignore_onetime=False)
    assert res == []


def test_submissions_call_with_submissions() -> None:
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": [""], "issues": {}}}
    sub = Submissions(
        JobConfig(
            product="",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "", "DISTRI": None},
            config=test_config,
        ),
        extrasettings=set(),
    )
    res = sub(submissions=[MockSubmission()], token={}, ci_url="", ignore_onetime=False)
    assert res == []


def test_submissions_call_with_issues() -> None:
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": [""], "issues": {"1234": ":"}}}
    sub = Submissions(
        JobConfig(
            product="",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "", "DISTRI": None},
            config=test_config,
        ),
        extrasettings=set(),
    )
    res = sub(submissions=[MockSubmission()], token={}, ci_url="", ignore_onetime=False)
    assert res == []


@pytest.fixture
def request_mock(mocker: MockerFixture) -> Generator[None, None, None]:
    class MockResponse:
        # mock json() method always returns a specific testing dictionary
        @staticmethod
        def json() -> list[dict]:
            return [{"flavor": None}]

    return mocker.patch("openqabot.types.submissions.retried_requests.get", return_value=MockResponse())


@pytest.mark.usefixtures("request_mock")
def test_submissions_call_with_channels() -> None:
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": [""], "issues": {"1234": ":"}}}

    sub = Submissions(
        JobConfig(
            product="",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "", "DISTRI": None},
            config=test_config,
        ),
        extrasettings=set(),
    )
    res = sub(
        submissions=[MockSubmission(channels=[Repos("", "", "")], rev_fallback_value=12345)],
        token={},
        ci_url="",
        ignore_onetime=False,
    )
    assert len(res) == 1


@pytest.mark.usefixtures("request_mock")
def test_submissions_call_with_packages() -> None:
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": [""], "issues": {"1234": ":"}, "packages": ["Donalduck"]}}

    sub = Submissions(
        JobConfig(
            product="",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "", "DISTRI": None},
            config=test_config,
        ),
        extrasettings=set(),
    )
    res = sub(
        submissions=[
            MockSubmission(channels=[Repos("", "", "")], rev_fallback_value=12345, contains_package_value=True)
        ],
        token={},
        ci_url="",
        ignore_onetime=False,
    )
    assert len(res) == 1


@pytest.mark.usefixtures("request_mock")
def test_submissions_call_with_params_expand() -> None:
    """Tests submissions call.

    Product configuration has 4 settings.
    Submission configuration has only 1 flavor.
    The only flavor is using params_expand.
    set of setting in product and flavor:
    - match on SOMETHING: flavor value has to win
    - flavor set extend product set SOMETHING_NEW:
    - one setting is only at product level SOMETHING_ELSE.
    """
    test_config = {}
    test_config["FLAVOR"] = {
        "AAA": {
            "archs": [""],
            "issues": {"1234": ":"},
            "packages": ["Donalduck"],
            "params_expand": {
                "SOMETHING": "flavor win",
                "SOMETHING_NEW": "something flavor specific",
            },
        },
    }

    sub = Submissions(
        JobConfig(
            product="",
            product_repo=None,
            product_version=None,
            settings={
                "VERSION": "",
                "DISTRI": None,
                "SOMETHING": "original",
                "SOMETHING_ELSE": "original_else",
            },
            config=test_config,
        ),
        extrasettings=set(),
    )
    res = sub(
        submissions=[
            MockSubmission(channels=[Repos("", "", "")], rev_fallback_value=12345, contains_package_value=True)
        ],
        token={},
        ci_url="",
        ignore_onetime=False,
    )
    assert len(res) == 1
    assert res[0]["openqa"]["SOMETHING"] == "flavor win"
    assert res[0]["openqa"]["SOMETHING_ELSE"] == "original_else"
    assert res[0]["openqa"]["SOMETHING_NEW"] == "something flavor specific"


@pytest.mark.usefixtures("request_mock")
def test_submissions_call_with_params_expand_distri_version() -> None:
    """DISTRI and VERSION settings cannot be changed using params_expand."""
    test_config = {}
    test_config["FLAVOR"] = {
        "AAA": {
            "archs": [""],
            "issues": {"1234": ":"},
            "packages": ["Donalduck"],
            "params_expand": {
                "DISTRI": "flavor distri",
                "SOMETHING": "flavor win",
            },
        },
        "BBB": {
            "archs": [""],
            "issues": {"1234": ":"},
            "packages": ["Donalduck"],
            "params_expand": {
                "VERSION": "flavor version",
                "SOMETHING": "flavor win",
            },
        },
        "CCC": {
            "archs": [""],
            "issues": {"1234": ":"},
            "packages": ["Donalduck"],
            "params_expand": {
                "SOMETHING": "flavor win",
            },
        },
    }

    sub = Submissions(
        JobConfig(
            product="",
            product_repo=None,
            product_version=None,
            settings={
                "VERSION": "1.2.3",
                "DISTRI": "IM_A_DISTRI",
                "SOMETHING": "original",
            },
            config=test_config,
        ),
        extrasettings=set(),
    )
    res = sub(
        submissions=[
            MockSubmission(channels=[Repos("", "", "")], rev_fallback_value=12345, contains_package_value=True)
        ],
        token={},
        ci_url="",
        ignore_onetime=False,
    )
    assert len(res) == 1
    assert res[0]["openqa"]["VERSION"] == "1.2.3"
    assert res[0]["openqa"]["DISTRI"] == "IM_A_DISTRI"
    assert res[0]["openqa"]["SOMETHING"] == "flavor win"


@pytest.mark.usefixtures("request_mock")
def test_submissions_call_with_params_expand_isolated() -> None:
    """Tests submissions call.

    Product configuration has 4 settings.
    Submission configuration has 2 flavors.
    Only the first flavor is using params_expand, the other is not.
    Test that POST for the second exactly and only contains the product settings.
    """
    test_config = {}
    test_config["FLAVOR"] = {
        "AAA": {
            "archs": [""],
            "issues": {"1234": ":"},
            "packages": ["Donalduck"],
            "params_expand": {
                "SOMETHING": "flavor win",
                "SOMETHING_NEW": "something flavor specific",
            },
        },
        "BBB": {
            "archs": [""],
            "issues": {"1234": ":"},
            "packages": ["Donalduck"],
        },
    }

    sub = Submissions(
        JobConfig(
            product="",
            product_repo=None,
            product_version=None,
            settings={
                "VERSION": "",
                "DISTRI": None,
                "SOMETHING": "original",
                "SOMETHING_ELSE": "original_else",
            },
            config=test_config,
        ),
        extrasettings=set(),
    )
    res = sub(
        submissions=[
            MockSubmission(channels=[Repos("", "", "")], rev_fallback_value=12345, contains_package_value=True)
        ],
        token={},
        ci_url="",
        ignore_onetime=False,
    )
    assert len(res) == 2
    assert res[1]["openqa"]["SOMETHING"] == "original"


class LimitArchsSubmission(MockSubmission):
    """A mock submission that produces different revisions depending on limit_archs."""

    def compute_revisions_for_product_repo(
        self,
        product_repo: list[str] | str | None,  # noqa: ARG002
        product_version: str | None,  # noqa: ARG002
        limit_archs: set[str] | None = None,
    ) -> bool:
        self.revisions = {ArchVer("x86_64", "15-SP3"): 9999} if limit_archs else {ArchVer("x86_64", "15-SP3"): 12345}
        return True


@pytest.mark.usefixtures("request_mock")
def test_submissions_call_reproduction_of_repeated_schedule(mocker: MockerFixture) -> None:
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}}}
    sub_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    sub = LimitArchsSubmission(channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=None)
    mock_jobs = [
        {
            "flavor": "AAA",
            "arch": "x86_64",
            "version": "15-SP3",
            "settings": {"REPOHASH": 12345},  # Global hash
        }
    ]
    mocker.patch("openqabot.types.submissions.retried_requests.get").return_value.json.return_value = mock_jobs
    res = sub_obj(submissions=[sub], token={}, ci_url="", ignore_onetime=False)
    assert res == []
