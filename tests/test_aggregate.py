# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import datetime
import logging
from collections.abc import Callable, Generator
from typing import Any

import pytest
import requests
from pytest_mock import MockerFixture

from openqabot.errors import SameBuildExistsError
from openqabot.types import Repos
from openqabot.types.aggregate import Aggregate
from openqabot.utc import UTC


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
def request_mock(mocker: MockerFixture) -> Generator[None, None, None]:
    mock_response = mocker.Mock()
    mock_response.json.return_value = [{}]
    return mocker.patch("openqabot.dashboard.retried_requests.get", return_value=mock_response)


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
    class MockIncident:
        def __init__(self, repo: Repos, *, embargoed: bool) -> None:
            self.id = 123
            self.livepatch = None
            self.staging = None
            self.channels = [repo]
            self.embargoed = embargoed

        def __str__(self) -> str:
            return str(self.id)

    def _func(product: str, version: str, arch: str, *, embargoed: bool = False) -> MockIncident:
        repo = Repos(product=product, version=version, arch=arch)
        return MockIncident(repo, embargoed=embargoed)

    return _func


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_with_test_issues(incident_mock: Callable[..., Any], mocker: MockerFixture) -> None:
    """Test with a valid incident."""
    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {"AAAAAAA": "BBBBBBBBB:CCCCCCCC"}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    inc = incident_mock(product="BBBBBBBBB", version="CCCCCCCC", arch="ciao")
    incidents = [inc]
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    res = acc(incidents=incidents, token=None, ci_url=None)
    assert len(res) == 1


PINT_IMAGE_MOCK = {"PUBLIC_CLOUD_IMAGE_ID": "Hola", "PUBLIC_CLOUD_TOOLS_IMAGE_BASE": "Base"}


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_pc_pint(mocker: MockerFixture) -> None:
    """Test with setting PUBLIC_CLOUD_PINT_QUERY to call apply_publiccloud_pint_image."""
    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {}
    my_settings = {"PUBLIC_CLOUD_PINT_QUERY": None}
    acc = Aggregate("", None, None, settings=my_settings, config=my_config)
    mocker.patch("openqabot.types.aggregate.apply_publiccloud_pint_image", return_value=PINT_IMAGE_MOCK)
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    acc(incidents=[], token=None, ci_url=None)


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_pc_pint_with_incidents(mocker: MockerFixture, incident_mock: Callable[..., Any]) -> None:
    """Test with incident and setting PUBLIC_CLOUD_PINT_QUERY to call apply_publiccloud_pint_image."""
    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {"AAAAAAA": "BBBBBBBBB:CCCCCCCC"}
    my_settings = {"PUBLIC_CLOUD_PINT_QUERY": None}
    acc = Aggregate("product", None, None, settings=my_settings, config=my_config)
    mocker.patch("openqabot.types.aggregate.apply_publiccloud_pint_image", return_value=PINT_IMAGE_MOCK)
    inc = incident_mock(product="BBBBBBBBB", version="CCCCCCCC", arch="ciao")
    incidents = [inc]
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    ret = acc(incidents=incidents, token=None, ci_url=None)
    assert ret[0]["openqa"]["PUBLIC_CLOUD_IMAGE_ID"] == "Hola"


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_no_job_settings(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    """Test with no job settings found."""
    caplog.set_level(10)  # DEBUG
    my_config = {"FLAVOR": "None", "archs": ["ciao"], "test_issues": {}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[])
    res = acc(incidents=[], token=None, ci_url=None)
    assert res == []
    assert "No aggregate jobs found for <Aggregate product: product> on arch ciao" in caplog.text


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_pc_tools_fail(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    """Test with pc tools image fetch failure."""
    caplog.set_level(logging.INFO)
    my_config = {"FLAVOR": "None", "archs": ["ciao"], "test_issues": {"I": "P:V"}}
    my_settings = {"PUBLIC_CLOUD_TOOLS_IMAGE_QUERY": "query"}
    acc = Aggregate("product", None, None, settings=my_settings, config=my_config)
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    mocker.patch("openqabot.types.aggregate.apply_pc_tools_image", return_value=None)

    inc = mocker.Mock()
    inc.channels = [Repos("P", "V", "ciao")]
    inc.livepatch = inc.staging = inc.embargoed = False
    inc.id = "I"
    res = acc(incidents=[inc], token=None, ci_url=None)
    assert res == []
    assert "No tools image found for <Aggregate product: product>" in caplog.text


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_pc_pint_fail(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    """Test with pc pint image fetch failure."""
    caplog.set_level(logging.INFO)
    my_config = {"FLAVOR": "None", "archs": ["ciao"], "test_issues": {"I": "P:V"}}
    my_settings = {"PUBLIC_CLOUD_PINT_QUERY": "query"}
    acc = Aggregate("product", None, None, settings=my_settings, config=my_config)
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    mocker.patch("openqabot.types.aggregate.apply_publiccloud_pint_image", return_value=None)

    inc = mocker.Mock()
    inc.channels = [Repos("P", "V", "ciao")]
    inc.livepatch = inc.staging = inc.embargoed = False
    inc.id = "I"
    res = acc(incidents=[inc], token=None, ci_url=None)
    assert res == []
    assert "No PINT image found for <Aggregate product: product>" in caplog.text


def test_get_buildnr_same_build() -> None:
    today = datetime.datetime.now(tz=UTC).date().strftime("%Y%m%d")
    with pytest.raises(SameBuildExistsError):
        Aggregate.get_buildnr("hash", "hash", today + "-1")


def test_filter_incidents_embargoed(incident_mock: Callable[..., Any], caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    my_config = {"FLAVOR": "None", "archs": [], "test_issues": {}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    acc.filter_embargoed = lambda _x: True
    incidents = [incident_mock(product="P", version="V", arch="A", embargoed=True)]
    res = acc._filter_incidents(incidents)  # noqa: SLF001
    assert res == []
    assert "skipped: Embargoed" in caplog.text


def test_filter_incidents_staging(incident_mock: Callable[..., Any]) -> None:
    my_config = {"FLAVOR": "None", "archs": [], "test_issues": {}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    inc = incident_mock(product="P", version="V", arch="A")
    inc.staging = True
    res = acc._filter_incidents([inc])  # noqa: SLF001
    assert res == []


def test_get_test_incidents_repos_existing(incident_mock: Callable[..., Any]) -> None:
    my_config = {"FLAVOR": "None", "archs": ["A"], "test_issues": {"ISSUES_1": "P:V"}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    inc = incident_mock(product="P", version="V", arch="A")
    inc.id = "I"
    # An incident that doesn't match to hit the false branch
    inc_mismatch = incident_mock(product="Other", version="V", arch="A")
    acc._get_test_incidents_and_repos([inc, inc_mismatch], "A")  # noqa: SLF001
    res_inc, res_repos = acc._get_test_incidents_and_repos([inc], "A")  # noqa: SLF001
    assert "ISSUES_1" in res_inc
    assert "REPOS_1" in res_repos


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_ci_url(mocker: MockerFixture) -> None:
    my_config = {"FLAVOR": "None", "archs": ["A"], "test_issues": {"I": "P:V"}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    mocker.patch("openqabot.types.aggregate.merge_repohash", return_value="hash")
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"build": "20220101-1", "repohash": "old"}])

    inc = mocker.Mock()
    inc.id = "I"
    inc.livepatch = inc.staging = inc.embargoed = False
    inc.channels = [Repos("P", "V", "A")]
    res = acc([inc], None, ci_url="http://ci")
    assert len(res) == 1
    assert res[0]["openqa"]["__CI_JOB_URL"] == "http://ci"


@pytest.mark.usefixtures("request_mock")
def test_process_arch_json_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    my_config = {"FLAVOR": "None", "archs": ["ciao"], "test_issues": {}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    mocker.patch("openqabot.types.aggregate.get_json", side_effect=requests.JSONDecodeError("msg", "doc", 0))
    res = acc(incidents=[], token=None, ci_url=None)
    assert res == []
    assert "Invalid JSON received for aggregate jobs" in caplog.text


@pytest.mark.usefixtures("request_mock")
def test_process_arch_request_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    my_config = {"FLAVOR": "None", "archs": ["ciao"], "test_issues": {}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    mocker.patch("openqabot.types.aggregate.get_json", side_effect=requests.RequestException("error"))
    res = acc(incidents=[], token=None, ci_url=None)
    assert res == []
    assert "Could not fetch previous aggregate jobs" in caplog.text


def test_process_arch_onetime_skip(mocker: MockerFixture) -> None:
    my_config = {"FLAVOR": "None", "archs": ["ciao"], "test_issues": {}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    acc.onetime = True
    mocker.patch("openqabot.types.aggregate.merge_repohash", return_value="new")

    today = datetime.datetime.now(tz=UTC).date().strftime("%Y%m%d")
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"build": today + "-1", "repohash": "old"}])
    res = acc._process_arch("ciao", [], {}, None, ignore_onetime=False)  # noqa: SLF001
    assert res is None


def test_aggregate_call_deprioritize_limit(mocker: MockerFixture) -> None:
    my_config = {"FLAVOR": "None", "archs": ["A"], "test_issues": {"I": "P:V"}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    mocker.patch("openqabot.types.aggregate.DEPRIORITIZE_LIMIT", 10)
    mocker.patch("openqabot.types.aggregate.merge_repohash", return_value="hash")
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"build": "old", "repohash": "old"}])

    inc = mocker.Mock()
    inc.id = "I"
    inc.livepatch = inc.staging = inc.embargoed = False
    inc.channels = [Repos("P", "V", "A")]
    res = acc([inc], None, ci_url=None)
    assert res[0]["openqa"]["_DEPRIORITIZE_LIMIT"] == 10


def test_aggregate_call_pc_tools_success(mocker: MockerFixture) -> None:
    my_config = {"FLAVOR": "None", "archs": ["A"], "test_issues": {"I": "P:V"}}
    my_settings = {"PUBLIC_CLOUD_TOOLS_IMAGE_QUERY": "query"}
    acc = Aggregate("product", None, None, settings=my_settings, config=my_config)
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    mocker.patch(
        "openqabot.types.aggregate.apply_pc_tools_image", return_value={"PUBLIC_CLOUD_TOOLS_IMAGE_BASE": "Base"}
    )
    inc = mocker.Mock()
    inc.id = "I"
    inc.livepatch = inc.staging = inc.embargoed = False
    inc.channels = [Repos("P", "V", "A")]
    res = acc([inc], None, ci_url=None)
    assert len(res) == 1
    assert res[0]["openqa"]["PUBLIC_CLOUD_TOOLS_IMAGE_BASE"] == "Base"


def test_process_arch_same_build_exists(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    my_config = {"FLAVOR": "None", "archs": ["A"], "test_issues": {"I": "P:V"}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    mocker.patch("openqabot.types.aggregate.merge_repohash", return_value="same")
    today = datetime.datetime.now(tz=UTC).date().strftime("%Y%m%d")
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"build": today + "-1", "repohash": "same"}])
    res = acc._process_arch("A", [], {}, None, ignore_onetime=False)  # noqa: SLF001
    assert res is None
    assert "A build with the same RepoHash already exists" in caplog.text
