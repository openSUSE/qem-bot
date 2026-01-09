# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Any

import pytest
from pytest_mock import MockerFixture

import responses
from openqabot.errors import NoRepoFoundError
from openqabot.types.incident import Incident
from openqabot.types.incidents import IncConfig, IncContext, Incidents
from openqabot.types.types import ArchVer, Repos


def test_incidents_constructor() -> None:
    """Test for the bare minimal set of arguments needed by the constructor."""
    test_config = {}
    test_config["FLAVOR"] = {}
    Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings={},
        config=test_config,
        extrasettings=set(),
    )


def test_incidents_printable() -> None:
    """Try the printable."""
    test_config = {}
    test_config["FLAVOR"] = {}
    inc = Incidents(
        product="hello",
        product_repo=None,
        product_version=None,
        settings={},
        config=test_config,
        extrasettings=set(),
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
        settings={},
        config=test_config,
        extrasettings=set(),
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
        settings={},
        config=test_config,
        extrasettings=set(),
    )
    res = inc(incidents=[], token={}, ci_url="", ignore_onetime=False)
    assert res == []


def _get_incidents_obj(
    test_config: dict | None = None, settings: dict | None = None, extrasettings: set | None = None
) -> Incidents:
    if test_config is None:
        test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    if settings is None:
        settings = {"VERSION": "15-SP3", "DISTRI": "SLES"}
    if extrasettings is None:
        extrasettings = set()
    return Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings=settings,
        config=test_config,
        extrasettings=extrasettings,
    )


def test_get_incidents_obj_coverage() -> None:
    _get_incidents_obj(test_config={"FLAVOR": {}}, settings={"V": "1"}, extrasettings=set())


@pytest.mark.parametrize(("rev_val", "fallback_val"), [(False, True), (True, None)])
def test_handle_incident_rev_coverage(mocker: MockerFixture, *, rev_val: bool, fallback_val: int | None) -> None:
    incidents_obj = _get_incidents_obj()
    inc = MockIncident()
    mocker.patch("openqabot.types.incidents.Incident.compute_revisions_for_product_repo", return_value=rev_val)
    mocker.patch("openqabot.types.incidents.Incident.revisions_with_fallback", return_value=fallback_val)
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data={})
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


class MockIncident(Incident):
    """A flexible mock implementation of Incident class for testing."""

    def __init__(self, **kwargs: Any) -> None:
        self.id = kwargs.get("id", 0)
        self.staging = kwargs.get("staging", False)
        self.livepatch = kwargs.get("livepatch", False)
        self.packages = kwargs.get("packages", ["pkg"])
        self.rrid = kwargs.get("rrid")
        self.revisions = kwargs.get("revisions", {})
        self.project = kwargs.get("project", "")
        self.ongoing = kwargs.get("ongoing", True)
        self.type = kwargs.get("type", "smelt")
        self.embargoed = kwargs.get("embargoed", False)
        self.channels = kwargs.get("channels", [])
        self.rr = kwargs.get("rr")
        self.priority = kwargs.get("priority")
        self.arch_filter = kwargs.get("arch_filter")
        self.emu = kwargs.get("emu", False)
        self.rev_fallback_value = kwargs.get("rev_fallback_value")
        self.contains_package_value = kwargs.get("contains_package_value")
        self.compute_revisions_value = kwargs.get("compute_revisions_value", True)

    def compute_revisions_for_product_repo(
        self,
        product_repo: list[str] | str | None,  # noqa: ARG002
        product_version: str | None,  # noqa: ARG002
    ) -> bool:
        return self.compute_revisions_value

    def revisions_with_fallback(self, arch: str, ver: str) -> int | None:
        if self.rev_fallback_value is not None:
            return self.rev_fallback_value
        if isinstance(self.revisions, dict):
            return self.revisions.get(ArchVer(arch, ver))
        return None

    def contains_package(self, requires: list[str]) -> bool:
        if self.contains_package_value is not None:
            return self.contains_package_value
        return any(p.startswith(tuple(requires)) for p in self.packages)


def test_mock_incident_contains_package_logic() -> None:
    inc = MockIncident(packages=["abc", "def"])
    assert inc.contains_package(["a"]) is True
    assert inc.contains_package(["x"]) is False


def test_mock_incident_revisions_with_fallback() -> None:
    inc = MockIncident()
    assert inc.revisions_with_fallback("x86_64", "15.0") is None


def test_incidents_call_with_incidents() -> None:
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": [""], "issues": {}}}
    inc = Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "", "DISTRI": None},
        config=test_config,
        extrasettings=set(),
    )
    res = inc(incidents=[MockIncident()], token={}, ci_url="", ignore_onetime=False)
    assert res == []


def test_incidents_call_with_issues() -> None:
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
    res = inc(incidents=[MockIncident()], token={}, ci_url="", ignore_onetime=False)
    assert res == []


@pytest.fixture
def request_mock(mocker: MockerFixture) -> Generator[None, None, None]:
    class MockResponse:
        # mock json() method always returns a specific testing dictionary
        @staticmethod
        def json() -> list[dict]:
            return [{"flavor": None}]

    return mocker.patch("openqabot.types.incidents.retried_requests.get", return_value=MockResponse())


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
    res = inc(
        incidents=[MockIncident(channels=[Repos("", "", "")], rev_fallback_value=12345)],
        token={},
        ci_url="",
        ignore_onetime=False,
    )
    assert len(res) == 1


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
    res = inc(
        incidents=[MockIncident(channels=[Repos("", "", "")], rev_fallback_value=12345, contains_package_value=True)],
        token={},
        ci_url="",
        ignore_onetime=False,
    )
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
    res = inc(
        incidents=[MockIncident(channels=[Repos("", "", "")], rev_fallback_value=12345, contains_package_value=True)],
        token={},
        ci_url="",
        ignore_onetime=False,
    )
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
    res = inc(
        incidents=[MockIncident(channels=[Repos("", "", "")], rev_fallback_value=12345, contains_package_value=True)],
        token={},
        ci_url="",
        ignore_onetime=False,
    )
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
    res = inc(
        incidents=[MockIncident(channels=[Repos("", "", "")], rev_fallback_value=12345, contains_package_value=True)],
        token={},
        ci_url="",
        ignore_onetime=False,
    )
    assert len(res) == 2
    assert res[1]["openqa"]["SOMETHING"] == "original"


@pytest.mark.usefixtures("request_mock")
def test_handle_incident_public_cloud_pint_query(mocker: MockerFixture) -> None:
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": [""], "issues": {"1234": ":"}}}

    mocker.patch("openqabot.types.incidents.apply_publiccloud_pint_image", return_value={"PUBLIC_CLOUD_IMAGE_ID": 1234})

    inc = Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "", "DISTRI": None, "PUBLIC_CLOUD_PINT_QUERY": None},
        config=test_config,
        extrasettings=set(),
    )
    res = inc(
        incidents=[MockIncident(channels=[Repos("", "", "")], rev_fallback_value=12345, contains_package_value=True)],
        token={},
        ci_url="",
        ignore_onetime=False,
    )
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
    inc = MockIncident()
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


def test_mock_incident_no_revisions() -> None:
    inc = MockIncident(revisions=None)
    assert inc.revisions_with_fallback("x86_64", "15.0") is None


def _assert_gitea_settings(
    result: dict,
    *,
    arch: str,
    flavor: str,
    inc_id: int,
    product_ver: str,
    repo_hash: int,
    expected_repo: str,
    distri: str,
) -> None:
    qem = result["qem"]
    assert qem["arch"] == arch
    assert qem["flavor"] == flavor
    assert qem["incident"] == inc_id
    assert qem["version"] == product_ver
    assert qem["withAggregate"]
    expected_settings = {
        "ARCH": arch,
        "BASE_TEST_ISSUES": str(inc_id),
        "BUILD": f":{inc_id}:pkg",
        "DISTRI": distri,
        "FLAVOR": flavor,
        "INCIDENT_ID": inc_id,
        "INCIDENT_REPO": f"{expected_repo}-{arch}/",
        "REPOHASH": repo_hash,
        "VERSION": product_ver,
    }
    for s in [result["openqa"], qem["settings"]]:
        actual = {k: s[k] for k in expected_settings}
        assert actual == expected_settings


@responses.activate
def test_gitea_incidents() -> None:
    product = "SUSE:SLFO"  # "product" is used to store the name of the codestream in Gitea-based incidents …
    version = "1.1.99:PullRequest:166:SLES"  # … and version is the full project including the product
    archs = ["x86_64", "aarch64"]
    product_ver = "15.99"
    settings = {"VERSION": product_ver, "DISTRI": "sles"}
    issues = {"BASE_TEST_ISSUES": "SLFO:1.1.99#15.99"}
    flavor = "AAA"
    test_config = {"FLAVOR": {flavor: {"archs": archs, "issues": issues}}}
    inc = MockIncident()
    inc.id = 42
    repo_hash = 12345
    inc.channels = [Repos(product, version, arch, product_ver) for arch in archs]
    inc.revisions = {ArchVer(arch, product_ver): repo_hash for arch in archs}
    inc.type = "git"
    incs = Incidents("SLFO", None, None, settings, test_config, set())
    incs.singlearch = set()
    expected_repo = "http://%REPO_MIRROR_HOST%/ibs/SUSE:/SLFO:/1.1.99:/PullRequest:/166:/SLES/product/repo/SLES-15.99"
    res = incs(incidents=[inc], token={}, ci_url="", ignore_onetime=False)
    assert len(res) == len(archs)
    for arch, result in zip(archs, res):
        _assert_gitea_settings(
            result,
            arch=arch,
            flavor=flavor,
            inc_id=inc.id,
            product_ver=product_ver,
            repo_hash=repo_hash,
            expected_repo=expected_repo,
            distri=settings["DISTRI"],
        )


def test_handle_incident_git_not_ongoing() -> None:
    inc_data = {
        "number": 123,
        "rr_number": 1,
        "project": "SUSE:Maintenance:123",
        "inReview": True,
        "isActive": False,
        "embargoed": False,
        "packages": ["foo"],
        "channels": ["SUSE:Updates:SLE-Product-SLES:15-SP3:x86_64"],
        "emu": False,
        "type": "git",
    }
    inc = Incident(inc_data)
    test_config = {"FLAVOR": {"AAA": {"archs": [""], "issues": {}}}}
    incidents_obj = Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "", "DISTRI": None},
        config=test_config,
        extrasettings=set(),
    )
    ctx = IncContext(inc=inc, arch="", flavor="AAA", data={})
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)

    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
    assert result is None


def test_handle_incident_with_ci_url(mocker: MockerFixture) -> None:
    inc_data = {
        "number": 123,
        "rr_number": 1,
        "project": "SUSE:Maintenance:123",
        "inReview": True,
        "isActive": True,
        "inReviewQAM": True,
        "approved": False,
        "embargoed": False,
        "packages": ["foo"],
        "channels": ["SUSE:Updates:SLE-Product-SLES:15-SP3:x86_64"],
        "emu": False,
        "type": "smelt",
    }
    inc = Incident(inc_data)

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLE-Product-SLES:15-SP3"}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo="SLE-Product-SLES",
        product_version="15-SP3",
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings=set(),
    )
    incidents_obj.singlearch = set()

    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=incidents_obj.flavors["AAA"])
    cfg = IncConfig(token={}, ci_url="http://my-ci.com/123", ignore_onetime=True)

    mocker.patch("openqabot.types.incident.get_max_revision", return_value=123)
    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001

    assert result is not None
    assert result["openqa"]["__CI_JOB_URL"] == "http://my-ci.com/123"


def test_is_scheduled_job_error(mocker: MockerFixture) -> None:
    inc = MockIncident()
    inc.id = 1
    mocker.patch("openqabot.types.incidents.retried_requests.get").return_value.json.return_value = {"error": "foo"}
    assert not Incidents._is_scheduled_job({}, inc, "arch", "ver", "flavor")  # noqa: SLF001


def test_is_scheduled_job_no_revs(mocker: MockerFixture) -> None:
    inc = MockIncident()
    inc.id = 1
    mocker.patch("openqabot.types.incidents.retried_requests.get").return_value.json.return_value = [{"id": 1}]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=None)
    assert not Incidents._is_scheduled_job({}, inc, "arch", "ver", "flavor")  # noqa: SLF001


def test_handle_incident_embargoed_skip() -> None:
    inc = MockIncident()
    inc.embargoed = True
    inc.id = 1
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings=set(),
    )
    # Patch filter_embargoed to return True
    incidents_obj.filter_embargoed = lambda _: True  # type: ignore[invalid-assignment]
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data={})
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


def test_handle_incident_staging_skip() -> None:
    inc = MockIncident()
    inc.staging = True
    inc.id = 1
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings=set(),
    )
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data={})
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


def test_handle_incident_packages_skip() -> None:
    inc = MockIncident(id=1, contains_package_value=False)
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings=set(),
    )
    data = {"packages": ["somepkg"]}
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=data)
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


def test_handle_incident_excluded_packages_skip() -> None:
    inc = MockIncident(id=1, contains_package_value=True)
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings=set(),
    )
    data = {"excluded_packages": ["badpkg"]}
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=data)
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


def test_handle_incident_livepatch_kgraft(mocker: MockerFixture) -> None:
    inc = MockIncident(
        id=1,
        livepatch=True,
        packages=["kernel-livepatch-foo"],
        channels=[Repos("SLES", "15-SP3", "x86_64")],
        rev_fallback_value=123,
    )

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings=set(),
    )
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=incidents_obj.flavors["AAA"])
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    # Mock _is_scheduled_job to return False
    mocker.patch.object(incidents_obj, "_is_scheduled_job", return_value=False)

    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
    assert result is not None
    assert result["openqa"]["KGRAFT"] == "1"


def test_handle_incident_no_issue_skip() -> None:
    inc = MockIncident(id=1, channels=[], rev_fallback_value=123)

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings=set(),
    )
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=incidents_obj.flavors["AAA"])
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


def test_handle_incident_required_issues_skip() -> None:
    inc = MockIncident(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)

    test_config = {
        "FLAVOR": {
            "AAA": {
                "archs": ["x86_64"],
                "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"},
                "required_issues": ["LTSS_TEST_ISSUES"],
            }
        }
    }
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings=set(),
    )
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=incidents_obj.flavors["AAA"])
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


def test_handle_incident_already_scheduled(mocker: MockerFixture) -> None:
    inc = MockIncident(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings=set(),
    )
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=incidents_obj.flavors["AAA"])
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(incidents_obj, "_is_scheduled_job", return_value=True)
    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


def test_handle_incident_kernel_no_product_repo_skip(mocker: MockerFixture) -> None:
    inc = MockIncident(id=1, livepatch=False, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)

    test_config = {
        "FLAVOR": {"SomeKernel-Flavor": {"archs": ["x86_64"], "issues": {"NOT_PRODUCT_REPO": "SLES:15-SP3"}}}
    }
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings=set(),
    )
    ctx = IncContext(
        inc=inc, arch="x86_64", flavor="SomeKernel-Flavor", data=incidents_obj.flavors["SomeKernel-Flavor"]
    )
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(incidents_obj, "_is_scheduled_job", return_value=False)

    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


def test_handle_incident_singlearch_no_aggregate(mocker: MockerFixture) -> None:
    inc = MockIncident(
        id=1, packages=["singlepkg"], channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123
    )

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings={"singlepkg"},
    )
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=incidents_obj.flavors["AAA"])
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(incidents_obj, "_is_scheduled_job", return_value=False)

    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
    assert result is not None
    assert result["qem"]["withAggregate"] is False


@pytest.mark.parametrize(
    "aggregate_check",
    [
        {"aggregate_check_true": ["OS_TEST_ISSUES"]},
        {"aggregate_check_false": ["OS_TEST_ISSUES"]},
        {"aggregate_check_false": ["SOMETHING_ELSE"]},
    ],
)
def test_handle_incident_should_aggregate_logic(mocker: MockerFixture, aggregate_check: dict) -> None:
    inc = MockIncident(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)

    flavor_data: dict[str, Any] = {
        "archs": ["x86_64"],
        "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"},
        "aggregate_job": False,
    }
    flavor_data.update(aggregate_check)

    test_config = {"FLAVOR": {"AAA": flavor_data}}
    incidents_obj = _get_incidents_obj(test_config=test_config)
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=incidents_obj.flavors["AAA"])
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(incidents_obj, "_is_scheduled_job", return_value=False)

    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
    assert result is not None
    assert result["qem"]["withAggregate"] is False


def test_handle_incident_params_expand_forbidden(mocker: MockerFixture) -> None:
    inc = MockIncident(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)

    test_config = {
        "FLAVOR": {
            "AAA": {
                "archs": ["x86_64"],
                "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"},
                "params_expand": {"DISTRI": "forbidden"},
            }
        }
    }
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings=set(),
    )
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=incidents_obj.flavors["AAA"])
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(incidents_obj, "_is_scheduled_job", return_value=False)

    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


def test_handle_incident_pc_tools_image_fail(mocker: MockerFixture) -> None:
    inc = MockIncident(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES", "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY": "test"},
        config=test_config,
        extrasettings=set(),
    )
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=incidents_obj.flavors["AAA"])
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(incidents_obj, "_is_scheduled_job", return_value=False)
    mocker.patch("openqabot.types.incidents.apply_pc_tools_image", return_value={})

    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


def test_handle_incident_pc_pint_image_fail(mocker: MockerFixture) -> None:
    inc = MockIncident(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES", "PUBLIC_CLOUD_PINT_QUERY": "test"},
        config=test_config,
        extrasettings=set(),
    )
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=incidents_obj.flavors["AAA"])
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(incidents_obj, "_is_scheduled_job", return_value=False)
    mocker.patch("openqabot.types.incidents.apply_publiccloud_pint_image", return_value={"PUBLIC_CLOUD_IMAGE_ID": None})

    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


def test_process_inc_context_norepfound(mocker: MockerFixture) -> None:
    inc = MockIncident(id=1, project="project", packages=["pkg"])
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings=set(),
    )
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data={"archs": ["x86_64"]})
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(incidents_obj, "_handle_incident", side_effect=NoRepoFoundError)

    assert incidents_obj._process_inc_context(ctx, cfg) is None  # noqa: SLF001


@pytest.mark.parametrize(
    ("inc_kwargs", "flavor_kwargs", "expected_prio"),
    [
        ({"emu": True, "staging": False}, {}, 30),
        ({"staging": False, "emu": False}, {}, 60),
        ({"staging": False, "emu": False}, {"override_priority": 50}, None),
        ({}, {"override_priority": 100}, 100),
        ({"staging": False}, {"flavor": "Minimal"}, 55),
    ],
)
def test_handle_incident_priority_logic(
    mocker: MockerFixture, inc_kwargs: dict, flavor_kwargs: dict, expected_prio: int | None
) -> None:
    flavor = flavor_kwargs.pop("flavor", "AAA")
    inc = MockIncident(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123, **inc_kwargs)

    flavor_data = {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}
    flavor_data.update(flavor_kwargs)

    test_config = {"FLAVOR": {flavor: flavor_data}}
    incidents_obj = _get_incidents_obj(test_config=test_config)
    ctx = IncContext(inc=inc, arch="x86_64", flavor=flavor, data=incidents_obj.flavors[flavor])
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(incidents_obj, "_is_scheduled_job", return_value=False)

    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
    assert result is not None
    if expected_prio is None:
        assert "_PRIORITY" not in result["openqa"]
    else:
        assert result["openqa"]["_PRIORITY"] == expected_prio


def test_handle_incident_pc_tools_image_success(mocker: MockerFixture) -> None:
    inc = MockIncident(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES", "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY": "test"},
        config=test_config,
        extrasettings=set(),
    )
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=incidents_obj.flavors["AAA"])
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(incidents_obj, "_is_scheduled_job", return_value=False)
    mocker.patch(
        "openqabot.types.incidents.apply_pc_tools_image",
        return_value={"PUBLIC_CLOUD_TOOLS_IMAGE_BASE": "some_image"},
    )

    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
    assert result is not None
    assert result["openqa"]["PUBLIC_CLOUD_TOOLS_IMAGE_BASE"] == "some_image"


def test_handle_incident_no_revisions_return_none() -> None:
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings=set(),
    )

    inc = MockIncident(id=1, rrid="RRID", revisions=None, channels=[])
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data={})
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)

    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


def test_handle_incident_compute_revisions_fail() -> None:
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"I": "p:v"}}}}
    incidents_obj = _get_incidents_obj(test_config=test_config)
    inc = MockIncident(compute_revisions_value=False, channels=[Repos("p", "v", "x86_64")])
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=incidents_obj.flavors["AAA"])
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)

    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


def test_handle_incident_revisions_fallback_none() -> None:
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"I": "p:v"}}}}
    incidents_obj = _get_incidents_obj(test_config=test_config)

    inc = MockIncident(
        id=1,
        rrid="RRID",
        compute_revisions_value=True,
        rev_fallback_value=None,
        channels=[Repos("p", "v", "x86_64")],
    )
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=incidents_obj.flavors["AAA"])
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


def test_should_skip_embargoed(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.INFO)
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings=set(),
    )
    # Enable embargo filtering for flavor AAA
    mocker.patch.object(incidents_obj, "filter_embargoed", return_value=True)

    inc = MockIncident(id=1, rrid="RRID", revisions=None, channels=[], embargoed=True)
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data={})
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)

    # This should trigger line 147-148 in openqabot/types/incidents.py
    assert incidents_obj._should_skip(ctx, cfg, {}) is True  # noqa: SLF001
    assert "Incident 1 skipped: Embargoed and embargo-filtering enabled" in caplog.text


def test_should_skip_kernel_missing_repo(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    incidents_obj = Incidents(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config={"FLAVOR": {}},
        extrasettings=set(),
    )
    inc = MockIncident(id=1, rrid="RRID", revisions=None, channels=[], livepatch=False)
    # Use flavor with "Kernel"
    ctx = IncContext(inc=inc, arch="x86_64", flavor="Kernel-Default", data={})
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)

    # Case 1: matches has something, but not in allowed set (disjoint is True)
    matches = {"OTHER_ISSUE": [Repos("p", "v", "a")]}
    assert incidents_obj._should_skip(ctx, cfg, matches) is True  # noqa: SLF001
    assert "Kernel incident missing product repository" in caplog.text

    # Case 2: matches has something in allowed set (disjoint is False)
    matches = {"OS_TEST_ISSUES": [Repos("p", "v", "a")]}
    assert incidents_obj._should_skip(ctx, cfg, matches) is False  # noqa: SLF001


@pytest.mark.parametrize(
    ("data", "matches", "expected", "log_msg"),
    [
        (
            {"aggregate_job": False, "aggregate_check_true": ["MATCH"]},
            {"MATCH", "OTHER"},
            False,
            "Incident 1: Aggregate job not required",
        ),
        (
            {"aggregate_job": False, "aggregate_check_false": ["MISSING"]},
            {"OTHER"},
            False,
            "Incident 1: Aggregate job not required",
        ),
        (
            {"aggregate_job": False, "aggregate_check_true": ["POS"], "aggregate_check_false": ["NEG"]},
            {"NEG"},
            True,
            None,
        ),
    ],
)
def test_is_aggregate_needed_logic(
    caplog: pytest.LogCaptureFixture, *, data: dict, matches: set, expected: bool, log_msg: str | None
) -> None:
    caplog.set_level(logging.INFO)
    incidents_obj = _get_incidents_obj(test_config={"FLAVOR": {}})
    inc = MockIncident(id=1, rrid="RRID", revisions=None, channels=[])
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=data)
    assert incidents_obj._is_aggregate_needed(ctx, matches) is expected  # noqa: SLF001
    if log_msg:
        assert log_msg in caplog.text
