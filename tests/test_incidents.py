# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Generator

import pytest
from pytest_mock import MockerFixture

import responses
from openqabot.errors import NoRepoFoundError
from openqabot.types import ArchVer, Repos
from openqabot.types.incident import Incident
from openqabot.types.incidents import IncConfig, IncContext, Incidents


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
        self.embargoed = False

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
def request_mock(mocker: MockerFixture) -> Generator[None, None, None]:
    class MockResponse:
        # mock json() method always returns a specific testing dictionary
        @staticmethod
        def json() -> list[dict]:
            return [{"flavor": None}]

    return mocker.patch("openqabot.types.incidents.retried_requests.get", return_value=MockResponse())


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
def test_incidents_call_public_cloud_pint_query(mocker: MockerFixture) -> None:
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
        extrasettings=None,
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
    inc = MyIncident_0()
    inc.id = 1
    mocker.patch("openqabot.types.incidents.retried_requests.get").return_value.json.return_value = {"error": "foo"}
    assert not Incidents._is_scheduled_job({}, inc, "arch", "ver", "flavor")  # noqa: SLF001


def test_is_scheduled_job_no_revs(mocker: MockerFixture) -> None:
    inc = MyIncident_0()
    inc.id = 1
    mocker.patch("openqabot.types.incidents.retried_requests.get").return_value.json.return_value = [{"id": 1}]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=None)
    assert not Incidents._is_scheduled_job({}, inc, "arch", "ver", "flavor")  # noqa: SLF001


def test_handle_incident_embargoed_skip() -> None:
    inc = MyIncident_0()
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
    incidents_obj.filter_embargoed = lambda _: True
    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data={})
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    assert incidents_obj._handle_incident(ctx, cfg) is None  # noqa: SLF001


def test_handle_incident_staging_skip() -> None:
    inc = MyIncident_0()
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
    inc = MyIncident_3()
    inc.id = 1
    # Mock contains_package to return False
    inc.contains_package = lambda _: False
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
    inc = MyIncident_3()
    inc.id = 1
    # Mock contains_package to return True for excluded check
    inc.contains_package = lambda _: True
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
    inc = MyIncident_3()
    inc.id = 1
    inc.livepatch = True
    inc.packages = ["kernel-livepatch-foo"]
    inc.channels = [Repos("SLES", "15-SP3", "x86_64")]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=123)

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
    assert result["openqa"]["KGRAFT"] == "1"


def test_handle_incident_no_issue_skip(mocker: MockerFixture) -> None:
    inc = MyIncident_3()
    inc.id = 1
    inc.channels = []
    mocker.patch.object(inc, "revisions_with_fallback", return_value=123)

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


def test_handle_incident_required_issues_skip(mocker: MockerFixture) -> None:
    inc = MyIncident_3()
    inc.id = 1
    inc.channels = [Repos("SLES", "15-SP3", "x86_64")]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=123)

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
    inc = MyIncident_3()
    inc.id = 1
    inc.channels = [Repos("SLES", "15-SP3", "x86_64")]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=123)

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
    inc = MyIncident_3()
    inc.id = 1
    inc.livepatch = False
    inc.channels = [Repos("SLES", "15-SP3", "x86_64")]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=123)

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
    inc = MyIncident_3()
    inc.id = 1
    inc.packages = ["singlepkg"]
    inc.channels = [Repos("SLES", "15-SP3", "x86_64")]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=123)

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
    assert result["qem"]["withAggregate"] is False


def test_handle_incident_should_aggregate_logic(mocker: MockerFixture) -> None:
    inc = MyIncident_3()
    inc.id = 1
    inc.channels = [Repos("SLES", "15-SP3", "x86_64")]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=123)

    test_config = {
        "FLAVOR": {
            "AAA": {
                "archs": ["x86_64"],
                "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"},
                "aggregate_job": False,
                "aggregate_check_true": ["OS_TEST_ISSUES"],
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

    # Test case 1: aggregate check true matches
    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
    assert result["qem"]["withAggregate"] is False

    # Test case 2: aggregate check false matches
    incidents_obj.flavors["AAA"]["aggregate_check_true"] = []
    incidents_obj.flavors["AAA"]["aggregate_check_false"] = ["OS_TEST_ISSUES"]
    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
    assert result["qem"]["withAggregate"] is False

    # Test case 3: nothing matches
    incidents_obj.flavors["AAA"]["aggregate_check_false"] = ["SOMETHING_ELSE"]
    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
    # _should_aggregate returns (neg and pos) which is (True and False) -> False
    # If _should_aggregate returns False, and not aggregate_job, withAggregate = False
    assert result["qem"]["withAggregate"] is False


def test_handle_incident_priority_emu(mocker: MockerFixture) -> None:
    inc = MyIncident_3()
    inc.id = 1
    inc.emu = True
    inc.staging = False
    inc.channels = [Repos("SLES", "15-SP3", "x86_64")]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=123)

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
    mocker.patch.object(incidents_obj, "_is_scheduled_job", return_value=False)

    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
    # BASE_PRIO(50) - 20 (emu) = 30
    assert result["openqa"]["_PRIORITY"] == 30


def test_handle_incident_params_expand_forbidden(mocker: MockerFixture) -> None:
    inc = MyIncident_3()
    inc.id = 1
    inc.channels = [Repos("SLES", "15-SP3", "x86_64")]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=123)

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
    inc = MyIncident_3()
    inc.id = 1
    inc.channels = [Repos("SLES", "15-SP3", "x86_64")]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=123)

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
    inc = MyIncident_3()
    inc.id = 1
    inc.channels = [Repos("SLES", "15-SP3", "x86_64")]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=123)

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
    inc = MyIncident_3()
    inc.id = 1
    inc.project = "project"
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


def test_handle_incident_priority_none(mocker: MockerFixture) -> None:
    inc = MyIncident_3()
    inc.id = 1
    inc.staging = False
    inc.emu = False
    inc.channels = [Repos("SLES", "15-SP3", "x86_64")]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=123)

    test_config = {
        "FLAVOR": {
            "Regular": {
                "archs": ["x86_64"],
                "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"},
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
    ctx = IncContext(inc=inc, arch="x86_64", flavor="Regular", data=incidents_obj.flavors["Regular"])
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(incidents_obj, "_is_scheduled_job", return_value=False)

    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
    # BASE_PRIO(50) + 10 (not staging) = 60
    assert result["openqa"]["_PRIORITY"] == 60

    # If we use override_priority = 50
    incidents_obj.flavors["Regular"]["override_priority"] = 50
    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
    assert "_PRIORITY" not in result["openqa"]


def test_handle_incident_pc_tools_image_success(mocker: MockerFixture) -> None:
    inc = MyIncident_3()
    inc.id = 1
    inc.channels = [Repos("SLES", "15-SP3", "x86_64")]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=123)

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
    assert result["openqa"]["PUBLIC_CLOUD_TOOLS_IMAGE_BASE"] == "some_image"


def test_handle_incident_priority_override(mocker: MockerFixture) -> None:
    inc = MyIncident_3()
    inc.id = 1
    inc.channels = [Repos("SLES", "15-SP3", "x86_64")]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=123)

    test_config = {
        "FLAVOR": {
            "AAA": {
                "archs": ["x86_64"],
                "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"},
                "override_priority": 100,
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

    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
    assert result["openqa"]["_PRIORITY"] == 100


def test_handle_incident_priority_minimal(mocker: MockerFixture) -> None:
    inc = MyIncident_3()
    inc.id = 1
    inc.staging = False
    inc.channels = [Repos("SLES", "15-SP3", "x86_64")]
    mocker.patch.object(inc, "revisions_with_fallback", return_value=123)

    test_config = {
        "FLAVOR": {
            "Minimal": {
                "archs": ["x86_64"],
                "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"},
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
    ctx = IncContext(inc=inc, arch="x86_64", flavor="Minimal", data=incidents_obj.flavors["Minimal"])
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(incidents_obj, "_is_scheduled_job", return_value=False)

    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
    # BASE_PRIO(50) + 10 (not staging) - 5 (Minimal) = 55
    assert result["openqa"]["_PRIORITY"] == 55
