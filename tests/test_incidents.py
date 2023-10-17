# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

from openqabot.types.incidents import Incidents
from unittest import mock
import pytest


def test_incidents_constructor():
    """
    What is the bare minimal set of arguments
    needed by the constructor?
    """
    test_config = {}
    test_config["FLAVOR"] = {}
    inc = Incidents(product="", settings=None, config=test_config, extrasettings=None)


def test_incidents_printable():
    """
    Try the printable
    """
    test_config = {}
    test_config["FLAVOR"] = {}
    inc = Incidents(
        product="hello", settings=None, config=test_config, extrasettings=None
    )
    assert "<Incidents product: hello>" == str(inc)


def test_incidents_call():
    """
    What is the bare minimal set of arguments
    needed by the callable?
    """
    test_config = {}
    test_config["FLAVOR"] = {}
    inc = Incidents(product="", settings=None, config=test_config, extrasettings=None)
    res = inc(incidents=[], token={}, ci_url="", ignore_onetime=False)
    assert res == []


def test_incidents_call_with_flavors():
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": []}}
    inc = Incidents(product="", settings=None, config=test_config, extrasettings=None)
    res = inc(incidents=[], token={}, ci_url="", ignore_onetime=False)
    assert res == []


class MyIncident_0(object):
    """
    The simpler possible implementation of Incident class
    """

    def __init__(self):
        self.id = None
        self.staging = False
        self.livepatch = False
        self.packages = [None]
        self.rrid = None
        self.revisions = {("", ""): None}

    def revisions_with_fallback(self, arch, version):
        pass


def test_incidents_call_with_incidents():
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": [""], "issues": {}}}
    inc = Incidents(
        product="",
        settings={"VERSION": "", "DISTRI": None},
        config=test_config,
        extrasettings=None,
    )
    res = inc(incidents=[MyIncident_0()], token={}, ci_url="", ignore_onetime=False)
    assert res == []


class MyIncident_1(MyIncident_0):
    def __init__(self):
        super().__init__()
        self.channels = []


def test_incidents_call_with_issues():
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": [""], "issues": {"1234": ":"}}}
    inc = Incidents(
        product="",
        settings={"VERSION": "", "DISTRI": None},
        config=test_config,
        extrasettings=None,
    )
    res = inc(incidents=[MyIncident_1()], token={}, ci_url="", ignore_onetime=False)
    assert res == []


@pytest.fixture
def request_mock(monkeypatch):
    """
    Aggregate is using requests to get old jobs
    from the QEM dashboard.
    At the moment the mock returned value
    is harcoded to [{}]
    """

    class MockResponse:
        # mock json() method always returns a specific testing dictionary
        @staticmethod
        def json():
            return [{"flavor": None}]

    def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr("openqabot.types.incidents.requests.get", mock_get)


class MyIncident_2(MyIncident_1):
    def __init__(self):
        super().__init__()
        self.channels = [("", "", "")]
        self.emu = False

    def revisions_with_fallback(self, arch, version):
        return True


def test_incidents_call_with_channels(request_mock):
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": [""], "issues": {"1234": ":"}}}

    inc = Incidents(
        product="",
        settings={"VERSION": "", "DISTRI": None},
        config=test_config,
        extrasettings=set(),
    )
    res = inc(incidents=[MyIncident_2()], token={}, ci_url="", ignore_onetime=False)
    assert len(res) == 1


class MyIncident_3(MyIncident_2):
    def __init__(self):
        super().__init__()
        self.channels = [("", "", "")]
        self.emu = False

    def contains_package(self, requires):
        return True


def test_incidents_call_with_packages(request_mock):
    test_config = {}
    test_config["FLAVOR"] = {
        "AAA": {"archs": [""], "issues": {"1234": ":"}, "packages": ["Donalduck"]}
    }

    inc = Incidents(
        product="",
        settings={"VERSION": "", "DISTRI": None},
        config=test_config,
        extrasettings=set(),
    )
    res = inc(incidents=[MyIncident_3()], token={}, ci_url="", ignore_onetime=False)
    assert len(res) == 1


def test_incidents_call_with_params_expand(request_mock):
    """
    Product configuration has 4 settings.
    Incident configuration has only 1 flavor.
    The only flavor is using params_expand.
    Set of setting in product and flavor:
    - match on SOMETHING: flavor value has to win
    - flavor set extend product set SOMETHING_NEW:
    - one setting is only at product level SOMETHING_ELSE
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
        }
    }

    inc = Incidents(
        product="",
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


def test_incidents_call_with_params_expand_distri_version(request_mock):
    """
    DISTRI and VERSION settings cannot be changed using params_expand.
    """
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


def test_incidents_call_with_params_expand_isolated(request_mock):
    """
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
    def __init__(self):
        super().__init__()
        self.embargoed = False


def test_incidents_call_public_cloud_pint_query(request_mock, monkeypatch):
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": [""], "issues": {"1234": ":"}}}

    monkeypatch.setattr(
        "openqabot.types.incidents.apply_publiccloud_pint_image",
        lambda *args, **kwargs: {"PUBLIC_CLOUD_IMAGE_ID": 1234},
    )

    inc = Incidents(
        product="",
        settings={"VERSION": "", "DISTRI": None, "PUBLIC_CLOUD_PINT_QUERY": None},
        config=test_config,
        extrasettings=set(),
    )
    res = inc(incidents=[MyIncident_4()], token={}, ci_url="", ignore_onetime=False)
    assert len(res) == 1
    assert "PUBLIC_CLOUD_IMAGE_ID" in res[0]["openqa"]
