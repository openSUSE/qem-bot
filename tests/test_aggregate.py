# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from typing import Any, Callable, Dict, List, NamedTuple

import pytest
from pytest import MonkeyPatch

from openqabot.types.aggregate import Aggregate


def test_aggregate_constructor() -> None:
    """What is the bare minimal set of arguments
    needed by the constructor?
    """
    config = {}
    config["FLAVOR"] = "None"
    config["archs"] = None
    config["test_issues"] = {}
    Aggregate("", None, None, None, config)


def test_aggregate_printable() -> None:
    """Try the printable"""
    config = {}
    config["FLAVOR"] = "None"
    config["archs"] = None
    config["test_issues"] = {}
    acc = Aggregate("hello", None, None, None, config)
    assert str(acc) == "<Aggregate product: hello>"


def test_aggregate_call() -> None:
    """What is the bare minimal set of arguments
    needed by the callable?
    """
    config = {}
    config["FLAVOR"] = "None"
    config["archs"] = []
    config["test_issues"] = {}
    acc = Aggregate("", None, None, None, config)
    res = acc(None, None, None)
    assert res == []


@pytest.fixture
def request_mock(monkeypatch: MonkeyPatch) -> None:
    """Aggregate is using requests to get old jobs
    from the QEM dashboard.
    At the moment the mock returned value
    is harcoded to [{}]
    """

    class MockResponse:
        # mock json() method always returns a specific testing dictionary
        @staticmethod
        def json() -> List[Dict[str, Any]]:
            return [{}]

    def mock_get(*_args: Any, **_kwargs: Any) -> MockResponse:
        return MockResponse()

    monkeypatch.setattr(
        "openqabot.dashboard.requests.get",
        mock_get,
    )


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_with_archs() -> None:
    """Configure an archs to enter in the function main loop"""
    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {}
    acc = Aggregate("", None, None, settings={}, config=my_config)
    res = acc(incidents=[], token=None, ci_url=None)
    assert res == []


@pytest.fixture
def incident_mock() -> Callable[..., Any]:
    """Simulate an incident class, reimplementing it in the simplest
    possible way that is accepted by Aggregate
    """

    class Repos(NamedTuple):
        product: str
        version: str
        arch: str
        product_version: str = ""

    class MockIncident:
        def __init__(self, repo: Repos, *, embargoed: bool) -> None:
            self.livepatch = None
            self.staging = None
            self.channels = [repo]
            self.embargoed = embargoed

    def _func(product: str, version: str, arch: str, *, embargoed: bool = False) -> MockIncident:
        repo = Repos(product=product, version=version, arch=arch)
        return MockIncident(repo, embargoed=embargoed)

    return _func


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_with_test_issues(incident_mock: Callable[..., Any]) -> None:
    """Test with a valid incident"""
    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {"AAAAAAA": "BBBBBBBBB:CCCCCCCC"}
    acc = Aggregate("", None, None, settings={}, config=my_config)
    res = acc(
        incidents=[incident_mock(product="BBBBBBBBB", version="CCCCCCCC", arch="ciao")],
        token=None,
        ci_url=None,
    )
    assert len(res) == 1


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_pc_pint(monkeypatch: MonkeyPatch) -> None:
    """Test with setting PUBLIC_CLOUD_PINT_QUERY to call apply_publiccloud_pint_image"""

    def mockreturn(_settings: Any) -> Dict[str, str]:
        return {"PUBLIC_CLOUD_IMAGE_ID": "Hola"}

    monkeypatch.setattr(
        "openqabot.types.aggregate.apply_publiccloud_pint_image",
        mockreturn,
    )

    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {}
    my_settings = {"PUBLIC_CLOUD_PINT_QUERY": None}
    acc = Aggregate("", None, None, settings=my_settings, config=my_config)
    acc(incidents=[], token=None, ci_url=None)


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_pc_pint_with_incidents(incident_mock: Callable[..., Any], monkeypatch: MonkeyPatch) -> None:
    """Test with incident and setting PUBLIC_CLOUD_PINT_QUERY to call apply_publiccloud_pint_image"""

    def mockreturn(_settings: Any) -> Dict[str, str]:
        return {"PUBLIC_CLOUD_IMAGE_ID": "Hola"}

    monkeypatch.setattr(
        "openqabot.types.aggregate.apply_publiccloud_pint_image",
        mockreturn,
    )
    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {"AAAAAAA": "BBBBBBBBB:CCCCCCCC"}
    my_settings = {"PUBLIC_CLOUD_PINT_QUERY": None}
    acc = Aggregate("", None, None, settings=my_settings, config=my_config)
    ret = acc(
        incidents=[incident_mock(product="BBBBBBBBB", version="CCCCCCCC", arch="ciao")],
        token=None,
        ci_url=None,
    )
    assert ret[0]["openqa"]["PUBLIC_CLOUD_IMAGE_ID"] == "Hola"
