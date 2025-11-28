# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from collections.abc import Callable, Generator
from typing import Any, NamedTuple
from unittest.mock import MagicMock, patch

import pytest

from openqabot.types.aggregate import Aggregate


def test_aggregate_constructor() -> None:
    """Test for the bare minimal set of arguments needed by the constructor."""
    config = {}
    config["FLAVOR"] = "None"
    config["archs"] = None
    config["test_issues"] = {}
    Aggregate("", None, None, None, config)


def test_aggregate_printable() -> None:
    """Try the printable."""
    config = {}
    config["FLAVOR"] = "None"
    config["archs"] = None
    config["test_issues"] = {}
    acc = Aggregate("hello", None, None, None, config)
    assert str(acc) == "<Aggregate product: hello>"


def test_aggregate_call() -> None:
    """Test for the bare minimal set of arguments needed by the callable."""
    config = {}
    config["FLAVOR"] = "None"
    config["archs"] = []
    config["test_issues"] = {}
    acc = Aggregate("", None, None, None, config)
    res = acc([], None, None)
    assert res == []


@pytest.fixture
def request_mock() -> Generator[None, None, None]:
    mock_response = MagicMock()
    mock_response.json.return_value = [{}]
    with patch("openqabot.dashboard.retried_requests.get", return_value=mock_response):
        yield


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_with_archs() -> None:
    """Configure an archs to enter in the function main loop."""
    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {}
    acc = Aggregate("", None, None, settings={}, config=my_config)
    res = acc(incidents=[], token=None, ci_url=None)
    assert res == []


@pytest.fixture
def incident_mock() -> Callable[..., Any]:
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
    """Test with a valid incident."""
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


PINT_IMAGE_MOCK = {"PUBLIC_CLOUD_IMAGE_ID": "Hola"}


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_pc_pint() -> None:
    """Test with setting PUBLIC_CLOUD_PINT_QUERY to call apply_publiccloud_pint_image."""
    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {}
    my_settings = {"PUBLIC_CLOUD_PINT_QUERY": None}
    acc = Aggregate("", None, None, settings=my_settings, config=my_config)
    with patch("openqabot.types.aggregate.apply_publiccloud_pint_image", return_value=PINT_IMAGE_MOCK):
        acc(incidents=[], token=None, ci_url=None)


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_pc_pint_with_incidents(incident_mock: Callable[..., Any]) -> None:
    """Test with incident and setting PUBLIC_CLOUD_PINT_QUERY to call apply_publiccloud_pint_image."""
    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {"AAAAAAA": "BBBBBBBBB:CCCCCCCC"}
    my_settings = {"PUBLIC_CLOUD_PINT_QUERY": None}
    acc = Aggregate("", None, None, settings=my_settings, config=my_config)
    with patch("openqabot.types.aggregate.apply_publiccloud_pint_image", return_value=PINT_IMAGE_MOCK):
        ret = acc(
            incidents=[incident_mock(product="BBBBBBBBB", version="CCCCCCCC", arch="ciao")],
            token=None,
            ci_url=None,
        )
        assert ret[0]["openqa"]["PUBLIC_CLOUD_IMAGE_ID"] == "Hola"
