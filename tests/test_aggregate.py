# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import datetime
import logging
from collections import defaultdict
from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from pytest_mock import MockerFixture

from openqabot.config import DEFAULT_SUBMISSION_TYPE
from openqabot.errors import SameBuildExistsError
from openqabot.types.aggregate import Aggregate, _PostData  # noqa: PLC2701
from openqabot.types.submission import Submission
from openqabot.types.types import Repos
from openqabot.utc import UTC


def test_aggregate_constructor() -> None:
    """Test for the bare minimal set of arguments needed by the constructor."""
    config = {}
    config["FLAVOR"] = "None"
    config["archs"] = None
    config["test_issues"] = {}
    Aggregate("", None, None, {}, config)


def test_aggregate_printable() -> None:
    """Try the printable."""
    config = {}
    config["FLAVOR"] = "None"
    config["archs"] = None
    config["test_issues"] = {}
    acc = Aggregate("hello", None, None, {}, config)
    assert str(acc) == "<Aggregate product: hello>"


def test_aggregate_call() -> None:
    """Test for the bare minimal set of arguments needed by the callable."""
    config = {}
    config["FLAVOR"] = "None"
    config["archs"] = []
    config["test_issues"] = {}
    acc = Aggregate("", None, None, {}, config)
    res = acc([], {}, None)
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
    res = acc(submissions=[], token={}, ci_url=None)
    assert res == []


@pytest.fixture
def submission_mock() -> Callable[..., Any]:
    class MockSubmission:
        def __init__(self, repo: Repos, *, embargoed: bool) -> None:
            self.id = 123
            self.livepatch = None
            self.staging = None
            self.channels = [repo]
            self.embargoed = embargoed
            self.type = DEFAULT_SUBMISSION_TYPE

        def __str__(self) -> str:
            return str(self.id)

    def _func(product: str, version: str, arch: str, *, embargoed: bool = False) -> MockSubmission:
        repo = Repos(product=product, version=version, arch=arch)
        return MockSubmission(repo, embargoed=embargoed)

    return _func


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_with_test_issues(submission_mock: Callable[..., Any], mocker: MockerFixture) -> None:
    """Test with a valid submission."""
    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {"AAAAAAA": "BBBBBBBBB:CCCCCCCC"}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    sub = submission_mock(product="BBBBBBBBB", version="CCCCCCCC", arch="ciao")
    submissions = [sub]
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    res = acc(submissions=submissions, token={}, ci_url=None)
    assert len(res) == 1


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_pc_pint(mocker: MockerFixture) -> None:
    """Test with setting PUBLIC_CLOUD_PINT_QUERY to call apply_publiccloud_pint_image."""
    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {}
    my_settings = {"PUBLIC_CLOUD_PINT_QUERY": None}
    acc = Aggregate("", None, None, settings=my_settings, config=my_config)
    mocker.patch(
        "openqabot.types.aggregate.apply_publiccloud_pint_image",
        return_value={"PUBLIC_CLOUD_IMAGE_ID": "Hola", "PUBLIC_CLOUD_TOOLS_IMAGE_BASE": "Base"},
    )
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    acc(submissions=[], token={}, ci_url=None)


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_pc_pint_with_submissions(mocker: MockerFixture, submission_mock: Callable[..., Any]) -> None:
    """Test with submission and setting PUBLIC_CLOUD_PINT_QUERY to call apply_publiccloud_pint_image."""
    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {"AAAAAAA": "BBBBBBBBB:CCCCCCCC"}
    my_settings = {"PUBLIC_CLOUD_PINT_QUERY": None}
    acc = Aggregate("product", None, None, settings=my_settings, config=my_config)
    mocker.patch(
        "openqabot.types.aggregate.apply_publiccloud_pint_image",
        return_value={"PUBLIC_CLOUD_IMAGE_ID": "Hola", "PUBLIC_CLOUD_TOOLS_IMAGE_BASE": "Base"},
    )
    sub = submission_mock(product="BBBBBBBBB", version="CCCCCCCC", arch="ciao")
    submissions = [sub]
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    ret = acc(submissions=submissions, token={}, ci_url=None)
    assert ret[0]["openqa"]["PUBLIC_CLOUD_IMAGE_ID"] == "Hola"


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_no_job_settings(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    """Test with no job settings found."""
    caplog.set_level(10)  # DEBUG
    my_config = {"FLAVOR": "None", "archs": ["ciao"], "test_issues": {}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[])
    res = acc(submissions=[], token={}, ci_url=None)
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

    sub = mocker.Mock()
    sub.channels = [Repos("P", "V", "ciao")]
    sub.livepatch = sub.staging = sub.embargoed = False
    sub.id = "I"
    res = acc(submissions=[sub], token={}, ci_url=None)
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

    sub = mocker.Mock()
    sub.channels = [Repos("P", "V", "ciao")]
    sub.livepatch = sub.staging = sub.embargoed = False
    sub.id = "I"
    res = acc(submissions=[sub], token={}, ci_url=None)
    assert res == []
    assert "No PINT image found for <Aggregate product: product>" in caplog.text


def test_get_buildnr_same_build() -> None:
    today = datetime.datetime.now(tz=UTC).date().strftime("%Y%m%d")
    with pytest.raises(SameBuildExistsError):
        Aggregate.get_buildnr("hash", "hash", today + "-1")


def test_filter_submissions_embargoed(submission_mock: Callable[..., Any], caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    my_config = {"FLAVOR": "None", "archs": [], "test_issues": {}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    acc.filter_embargoed = lambda _x: True  # type: ignore[invalid-assignment]
    submissions = [submission_mock(product="P", version="V", arch="A", embargoed=True)]
    res = acc._filter_submissions(submissions)  # noqa: SLF001
    assert res == []
    assert "skipped: Embargoed" in caplog.text


def test_filter_submissions_staging(submission_mock: Callable[..., Any]) -> None:
    my_config = {"FLAVOR": "None", "archs": [], "test_issues": {}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    sub = submission_mock(product="P", version="V", arch="A")
    sub.staging = True
    res = acc._filter_submissions([sub])  # noqa: SLF001
    assert res == []


def test_get_test_submissions_repos_existing(submission_mock: Callable[..., Any]) -> None:
    my_config = {"FLAVOR": "None", "archs": ["A"], "test_issues": {"ISSUES_1": "P:V"}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    sub = submission_mock(product="P", version="V", arch="A")
    sub.id = "I"
    # A submission that doesn't match to hit the false branch
    sub_mismatch = submission_mock(product="Other", version="V", arch="A")
    acc._get_test_submissions_and_repos([sub, sub_mismatch], "A")  # noqa: SLF001
    res_sub, res_repos = acc._get_test_submissions_and_repos([sub], "A")  # noqa: SLF001
    assert "ISSUES_1" in res_sub
    assert "REPOS_1" in res_repos


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_ci_url(mocker: MockerFixture) -> None:
    my_config = {"FLAVOR": "None", "archs": ["A"], "test_issues": {"I": "P:V"}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    mocker.patch("openqabot.types.aggregate.merge_repohash", return_value="hash")
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"build": "20220101-1", "repohash": "old"}])

    sub = mocker.Mock()
    sub.id = "I"
    sub.livepatch = sub.staging = sub.embargoed = False
    sub.channels = [Repos("P", "V", "A")]
    res = acc([sub], {}, ci_url="http://ci")
    assert len(res) == 1
    assert res[0]["openqa"]["__CI_JOB_URL"] == "http://ci"


@pytest.mark.usefixtures("request_mock")
def test_process_arch_json_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    my_config = {"FLAVOR": "None", "archs": ["ciao"], "test_issues": {}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    mocker.patch("openqabot.types.aggregate.get_json", side_effect=requests.JSONDecodeError("msg", "doc", 0))
    res = acc(submissions=[], token={}, ci_url=None)
    assert res == []
    assert "Invalid JSON received for aggregate jobs" in caplog.text


@pytest.mark.usefixtures("request_mock")
def test_process_arch_request_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    my_config = {"FLAVOR": "None", "archs": ["ciao"], "test_issues": {}}
    acc = Aggregate("product", None, None, settings={}, config=my_config)
    mocker.patch("openqabot.types.aggregate.get_json", side_effect=requests.RequestException("error"))
    res = acc(submissions=[], token={}, ci_url=None)
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

    sub = mocker.Mock()
    sub.id = "I"
    sub.livepatch = sub.staging = sub.embargoed = False
    sub.channels = [Repos("P", "V", "A")]
    res = acc([sub], {}, ci_url=None)
    assert res[0]["openqa"]["_DEPRIORITIZE_LIMIT"] == 10


def test_aggregate_call_pc_tools_success(mocker: MockerFixture) -> None:
    my_config = {"FLAVOR": "None", "archs": ["A"], "test_issues": {"I": "P:V"}}
    my_settings = {"PUBLIC_CLOUD_TOOLS_IMAGE_QUERY": "query"}
    acc = Aggregate("product", None, None, settings=my_settings, config=my_config)
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    mocker.patch(
        "openqabot.types.aggregate.apply_pc_tools_image", return_value={"PUBLIC_CLOUD_TOOLS_IMAGE_BASE": "Base"}
    )
    sub = mocker.Mock()
    sub.id = "I"
    sub.livepatch = sub.staging = sub.embargoed = False
    sub.channels = [Repos("P", "V", "A")]
    res = acc([sub], {}, ci_url=None)
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


def test_aggregate_duplicate_submissions() -> None:
    # Minimal aggregate setup
    agg = Aggregate(
        product="SLES",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "15-SP3", "DISTRI": "sles"},
        config={"FLAVOR": "AAA", "archs": ["x86_64"], "test_issues": {"ISSUE": "product:version"}},
    )

    # Mock submissions with same ID
    sub1 = MagicMock(spec=Submission)
    sub1.id = 123
    sub1.livepatch = False
    sub1.staging = False
    sub1.embargoed = False
    sub1.type = DEFAULT_SUBMISSION_TYPE
    sub2 = MagicMock(spec=Submission)
    sub2.id = 123
    sub2.livepatch = False
    sub2.staging = False
    sub2.embargoed = False
    sub2.type = DEFAULT_SUBMISSION_TYPE

    test_submissions = defaultdict(list)
    test_submissions["ISSUE"] = [sub1, sub2]
    test_repos = defaultdict(list)
    test_repos["REPOS"] = ["repo"]

    post_data = _PostData(test_submissions, test_repos, "hash", "build")

    # Call _create_full_post directly
    res = agg._create_full_post("x86_64", post_data, None)  # noqa: SLF001

    # Verify unique incidents
    assert res is not None
    assert len(res["qem"]["incidents"]) == 1
    assert res["qem"]["incidents"][0] == 123
