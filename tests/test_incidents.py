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
    test_config = {"FLAVOR": {}}
    inc = Incidents(product="", settings=None, config=test_config, extrasettings=None)


def test_incidents_printable():
    """
    Try the printable
    """
    test_config = {"FLAVOR": {}}
    inc = Incidents(
        product="hello", settings=None, config=test_config, extrasettings=None
    )
    assert "<Incidents product: hello>" == str(inc)


def test_incidents_call():
    """
    What is the bare minimal set of arguments
    needed by the callable?
    """
    test_config = {"FLAVOR": {}}
    inc = Incidents(product="", settings=None, config=test_config, extrasettings=None)
    res = inc(incidents=[], token={}, ci_url="", ignore_onetime=False)
    assert res == []


def test_incidents_call_with_flavors():
    test_config = {}
    test_config["FLAVOR"] = {"AAA": {"archs": []}}
    inc = Incidents(product="", settings=None, config=test_config, extrasettings=None)
    res = inc(incidents=[], token={}, ci_url="", ignore_onetime=False)
    assert res == []


@pytest.fixture
def incidents_default():
    def _call(
        test_config, extrasettings=None, settings={"VERSION": "", "DISTRI": None}
    ):
        return Incidents(
            product="",
            settings=settings,
            config=test_config,
            extrasettings=extrasettings,
        )

    return _call


def test_incidents_call_with_incidents(incidents_default):
    class MyIncident(object):
        def __init__(self):
            self.id = None
            self.staging = False
            self.livepatch = False
            self.packages = [None]
            self.rrid = None
            self.revisions = {("", ""): None}

        def revisions_with_fallback(self, arch, version):
            pass

    test_config = {"FLAVOR": {"AAA": {"archs": [""], "issues": {}}}}
    inc = incidents_default(test_config)
    res = inc(incidents=[MyIncident()], token={}, ci_url="", ignore_onetime=False)
    assert res == []


def test_incidents_call_with_issues(incidents_default):
    class MyIncident(object):
        def __init__(self):
            self.id = None
            self.staging = False
            self.livepatch = False
            self.packages = [None]
            self.rrid = None
            self.revisions = {("", ""): None}
            self.channels = []

        def revisions_with_fallback(self, arch, version):
            pass

    test_config = {"FLAVOR": {"AAA": {"archs": [""], "issues": {"1234": ":"}}}}
    inc = incidents_default(test_config)
    res = inc(incidents=[MyIncident()], token={}, ci_url="", ignore_onetime=False)
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


def test_incidents_call_with_channels(request_mock, incidents_default):
    class MyIncident(object):
        def __init__(self):
            self.id = None
            self.staging = False
            self.livepatch = False
            self.packages = [None]
            self.rrid = None
            self.revisions = {("", ""): None}
            self.channels = [("", "", "")]
            self.emu = False

        def revisions_with_fallback(self, arch, version):
            return True

    test_config = {"FLAVOR": {"AAA": {"archs": [""], "issues": {"1234": ":"}}}}
    inc = incidents_default(test_config, extrasettings=set())
    res = inc(incidents=[MyIncident()], token={}, ci_url="", ignore_onetime=False)
    assert len(res) == 1


def test_incidents_call_public_cloud_pint_query(
    request_mock, monkeypatch, incidents_default
):
    class MyIncident(object):
        def __init__(self):
            self.id = None
            self.staging = False
            self.livepatch = False
            self.packages = [None]
            self.rrid = None
            self.revisions = {("", ""): None}
            self.channels = [("", "", "")]
            self.emu = False
            self.embargoed = False

        def revisions_with_fallback(self, arch, version):
            return True

    monkeypatch.setattr(
        "openqabot.types.incidents.apply_publiccloud_pint_image",
        lambda *args, **kwargs: {"PUBLIC_CLOUD_IMAGE_ID": 1234},
    )

    test_config = {"FLAVOR": {"AAA": {"archs": [""], "issues": {"1234": ":"}}}}
    pc_settings = {"VERSION": "", "DISTRI": None, "PUBLIC_CLOUD_PINT_QUERY": None}
    inc = incidents_default(test_config, extrasettings=set(), settings=pc_settings)
    res = inc(incidents=[MyIncident()], token={}, ci_url="", ignore_onetime=False)
    assert len(res) == 1
    assert "PUBLIC_CLOUD_IMAGE_ID" in res[0]["openqa"]
