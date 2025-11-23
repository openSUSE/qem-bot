# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

import pytest

import responses
from openqabot.types import ArchVer, Repos
from openqabot.types.incidents import Incidents


def test_incidents_constructor() -> None:
    """Test for the bare minimal set of arguments needed by the constructor."""
    test_config = {}
    test_config["FLAVOR"] = {}
    Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings=None,
        config=test_config,
        extrasettings=None,
    )


def test_incidents_printable() -> None:
    """Try the printable."""
    test_config = {}
    test_config["FLAVOR"] = {}
    inc = Incidents(
        product="hello",
        product_repo=None,
        product_version=None,
        settings=None,
        config=test_config,
        extrasettings=None,
    )
    assert str(inc) == "<Incidents product: hello>"


def test_incidents_call() -> None:
    """Test for the bare minimal set of arguments needed by the callable."""
    test_config = {}
    test_config["FLAVOR"] = {}
    inc = Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings=None,
        config=test_config,
        extrasettings=None,
    )
    res = inc(incidents=[], token={}, ci_url="", ignore_onetime=False)
    assert res == []


def test_incidents_call_with_flavors() -> None:
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": []}}
    inc = Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings=None,
        config=test_config,
        extrasettings=None,
    )
    res = inc(incidents=[], token={}, ci_url="", ignore_onetime=False)
    assert res == []


class MyIncident_0:
    """The simpler possible implementation of Incident class."""

    def __init__(self) -> None:
        self.id = None
        self.staging = False
        self.livepatch = False
        self.packages = [None]
        self.rrid = None
        self.revisions = {("", ""): None}
        self.project = None
        self.ongoing = True
        self.type = "smelt"

    def compute_revisions_for_product_repo(self, product_repo: str | None, product_version: str | None) -> None:
        pass

    def revisions_with_fallback(self, arch: str, version: str) -> None:
        pass


def test_incidents_call_with_incidents() -> None:
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": [""], "issues": {}}}
    inc = Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "", "DISTRI": None},
        config=test_config,
        extrasettings=None,
    )
    res = inc(incidents=[MyIncident_0()], token={}, ci_url="", ignore_onetime=False)
    assert res == []


class MyIncident_1(MyIncident_0):
    def __init__(self) -> None:
        super().__init__()
        self.channels = []


def test_incidents_call_with_issues() -> None:
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": [""], "issues": {"1234": ":"}}}
    inc = Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "", "DISTRI": None},
        config=test_config,
        extrasettings=None,
    )
    res = inc(incidents=[MyIncident_1()], token={}, ci_url="", ignore_onetime=False)
    assert res == []


@pytest.fixture
def request_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    class MockResponse:
        # mock json() method always returns a specific testing dictionary
        @staticmethod
        def json() -> list[dict]:
            return [{"flavor": None}]

    def mock_get(*_args: Any, **_kwargs: Any) -> MockResponse:
        return MockResponse()

    monkeypatch.setattr("openqabot.types.incidents.retried_requests.get", mock_get)


class MyIncident_2(MyIncident_1):
    def __init__(self) -> None:
        super().__init__()
        self.channels = [Repos("", "", "")]
        self.emu = False

    def revisions_with_fallback(self, _arch: str, _version: str) -> bool:
        return True


@pytest.mark.usefixtures("request_mock")
def test_incidents_call_with_channels() -> None:
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": [""], "issues": {"1234": ":"}}}

    inc = Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "", "DISTRI": None},
        config=test_config,
        extrasettings=set(),
    )
    res = inc(incidents=[MyIncident_2()], token={}, ci_url="", ignore_onetime=False)
    assert len(res) == 1


class MyIncident_3(MyIncident_2):
    def __init__(self) -> None:
        super().__init__()
        self.channels = [Repos("", "", "")]
        self.emu = False

    def contains_package(self, _requires: list[str]) -> bool:
        return True


@pytest.mark.usefixtures("request_mock")
def test_incidents_call_with_packages() -> None:
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": [""], "issues": {"1234": ":"}, "packages": ["Donalduck"]}}

    inc = Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "", "DISTRI": None},
        config=test_config,
        extrasettings=set(),
    )
    res = inc(incidents=[MyIncident_3()], token={}, ci_url="", ignore_onetime=False)
    assert len(res) == 1


@pytest.mark.usefixtures("request_mock")
def test_incidents_call_with_params_expand() -> None:
    """Tests incidents call.

    Product configuration has 4 settings.
    Incident configuration has only 1 flavor.
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

    inc = Incidents(
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
        extrasettings=set(),
    )
    res = inc(incidents=[MyIncident_3()], token={}, ci_url="", ignore_onetime=False)
    assert len(res) == 1
    assert res[0]["openqa"]["SOMETHING"] == "flavor win"
    assert res[0]["openqa"]["SOMETHING_ELSE"] == "original_else"
    assert res[0]["openqa"]["SOMETHING_NEW"] == "something flavor specific"


@pytest.mark.usefixtures("request_mock")
def test_incidents_call_with_params_expand_distri_version() -> None:
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

    inc = Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings={
            "VERSION": "1.2.3",
            "DISTRI": "IM_A_DISTRI",
            "SOMETHING": "original",
        },
        config=test_config,
        extrasettings=set(),
    )
    res = inc(incidents=[MyIncident_3()], token={}, ci_url="", ignore_onetime=False)
    assert len(res) == 1
    assert res[0]["openqa"]["VERSION"] == "1.2.3"
    assert res[0]["openqa"]["DISTRI"] == "IM_A_DISTRI"
    assert res[0]["openqa"]["SOMETHING"] == "flavor win"


@pytest.mark.usefixtures("request_mock")
def test_incidents_call_with_params_expand_isolated() -> None:
    """Tests incidents call.

    Product configuration has 4 settings.
    Incident configuration has 2 flavors.
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

    inc = Incidents(
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
        extrasettings=set(),
    )
    res = inc(incidents=[MyIncident_3()], token={}, ci_url="", ignore_onetime=False)
    assert len(res) == 2
    assert res[1]["openqa"]["SOMETHING"] == "original"


class MyIncident_4(MyIncident_3):
    def __init__(self) -> None:
        super().__init__()
        self.embargoed = False


@pytest.mark.usefixtures("request_mock")
def test_incidents_call_public_cloud_pint_query(monkeypatch: pytest.MonkeyPatch) -> None:
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": [""], "issues": {"1234": ":"}}}

    monkeypatch.setattr(
        "openqabot.types.incidents.apply_publiccloud_pint_image",
        lambda *_args, **_kwargs: {"PUBLIC_CLOUD_IMAGE_ID": 1234},
    )

    inc = Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "", "DISTRI": None, "PUBLIC_CLOUD_PINT_QUERY": None},
        config=test_config,
        extrasettings=set(),
    )
    res = inc(incidents=[MyIncident_4()], token={}, ci_url="", ignore_onetime=False)
    assert len(res) == 1
    assert "PUBLIC_CLOUD_IMAGE_ID" in res[0]["openqa"]


def test_making_repo_url() -> None:
    s = {"VERSION": "", "DISTRI": None}
    c = {"FLAVOR": {"AAA": {"archs": [""], "issues": {"1234": ":"}}}}
    incs = Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings=s,
        config=c,
        extrasettings=set(),
    )
    inc = MyIncident_0()
    inc.id = 42
    exp_repo_start = "http://%REPO_MIRROR_HOST%/ibs/SUSE:/Maintenance:/42/"
    repo = incs._make_repo_url(inc, Repos("openSUSE", "15.7", "x86_64"))  # noqa: SLF001
    assert repo == exp_repo_start + "SUSE_Updates_openSUSE_15.7_x86_64"
    repo = incs._make_repo_url(inc, Repos("openSUSE-SLE", "15.7", "x86_64"))  # noqa: SLF001
    assert repo == exp_repo_start + "SUSE_Updates_openSUSE-SLE_15.7"
    slfo_chan = Repos("SUSE:SLFO", "SUSE:SLFO:1.1.99:PullRequest:166:SLES", "x86_64", "15.99")
    repo = incs._make_repo_url(inc, slfo_chan)  # noqa: SLF001
    exp_repo = "http://%REPO_MIRROR_HOST%/ibs/SUSE:/SLFO:/SUSE:/SLFO:/1.1.99:/PullRequest:/166:/SLES/product/repo/SLES-15.99-x86_64/"
    assert repo == exp_repo


class MyIncident_5(MyIncident_2):
    def revisions_with_fallback(self, arch: str, version: str) -> int:
        return self.revisions[ArchVer(arch, version)]


@responses.activate
def test_gitea_incidents() -> None:
    # declare fields of Repos used in this test
    product = "SUSE:SLFO"  # "product" is used to store the name of the codestream in Gitea-based incidents …
    version = "1.1.99:PullRequest:166:SLES"  # … and version is the full project including the product
    archs = ["x86_64", "aarch64"]
    product_ver = "15.99"

    # declare meta-data
    settings = {"VERSION": product_ver, "DISTRI": "sles"}
    issues = {"BASE_TEST_ISSUES": "SLFO:1.1.99#15.99"}
    flavor = "AAA"
    test_config = {"FLAVOR": {flavor: {"archs": archs, "issues": issues}}}

    # create a Git-based incident
    inc = inc = MyIncident_5()
    inc.id = 42
    repo_hash = 12345
    inc.channels = [Repos(product, version, arch, product_ver) for arch in archs]
    inc.revisions = {ArchVer(arch, product_ver): repo_hash for arch in archs}
    inc.type = "git"

    # compute openQA/dashboard settings for incident and check results
    incs = Incidents("SLFO", None, None, settings, test_config, None)
    incs.singlearch = set()
    expected_repo = "http://%REPO_MIRROR_HOST%/ibs/SUSE:/SLFO:/1.1.99:/PullRequest:/166:/SLES/product/repo/SLES-15.99"
    res = incs(incidents=[inc], token={}, ci_url="", ignore_onetime=False)
    assert len(res) == len(archs)
    for arch, result in zip(archs, res, strict=False):
        qem = result["qem"]
        computed_settings = [result["openqa"], qem["settings"]]
        assert qem["arch"] == arch
        assert qem["flavor"] == flavor
        assert qem["incident"] == inc.id
        assert qem["version"] == product_ver
        assert qem["withAggregate"]
        for s in computed_settings:
            assert s["ARCH"] == arch
            assert s["BASE_TEST_ISSUES"] == str(inc.id)
            assert s["BUILD"] == f":{inc.id}:None"
            assert s["DISTRI"] == settings["DISTRI"]
            assert s["FLAVOR"] == flavor
            assert s["INCIDENT_ID"] == inc.id
            assert s["INCIDENT_REPO"] == f"{expected_repo}-{arch}/"
            assert s["REPOHASH"] == repo_hash
            assert s["VERSION"] == product_ver
