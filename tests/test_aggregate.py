# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test aggregate."""

from __future__ import annotations

import datetime
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

import pytest
import requests

from openqabot.config import DEFAULT_SUBMISSION_TYPE
from openqabot.errors import SameBuildExistsError
from openqabot.types.aggregate import Aggregate, PostData
from openqabot.types.baseconf import JobConfig
from openqabot.types.submission import Submission
from openqabot.types.types import Repos
from openqabot.utc import UTC

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture


@pytest.fixture
def config() -> dict[str, Any]:
    return {"FLAVOR": "None", "archs": ["ciao"], "test_issues": {}}


@pytest.fixture
def aggregate_factory() -> Any:
    def _factory(product: str = "", settings: dict | None = None, config: dict | None = None) -> Aggregate:
        return Aggregate(
            JobConfig(product, None, None, settings or {}, config or {"FLAVOR": "None", "archs": [], "test_issues": {}})
        )

    return _factory


@pytest.fixture
def submission_mock(mocker: MockerFixture) -> Any:
    def _func(
        product: str = "P", version: str = "V", arch: str = "A", *, embargoed: bool = False, staging: bool = False
    ) -> MagicMock:
        sub = mocker.MagicMock(spec=Submission)
        sub.id = 123
        sub.livepatch = None
        sub.staging = staging
        sub.channels = [Repos(product=product, version=version, arch=arch)]
        sub.embargoed = embargoed
        sub.type = DEFAULT_SUBMISSION_TYPE
        sub.priority = None
        sub.__str__.return_value = str(sub.id)
        return sub

    return _func


@pytest.fixture
def request_mock(mocker: MockerFixture) -> Any:
    mock_response = mocker.Mock()
    mock_response.json.return_value = [{}]
    return mocker.patch("openqabot.dashboard.retried_requests.get", return_value=mock_response)


def test_aggregate_constructor() -> None:
    """Test for the bare minimal set of arguments needed by the constructor."""
    Aggregate(JobConfig("", None, None, {}, {"FLAVOR": "None", "archs": None, "test_issues": {}}))


def test_aggregate_printable(aggregate_factory: Any) -> None:
    """Try the printable."""
    acc = aggregate_factory("hello")
    assert str(acc) == "<Aggregate product: hello>"


def test_aggregate_call(aggregate_factory: Any) -> None:
    """Test for the bare minimal set of arguments needed by the callable."""
    acc = aggregate_factory()
    assert acc([], {}, None) == []


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_with_archs(aggregate_factory: Any, config: dict) -> None:
    """Configure an archs to enter in the function main loop."""
    acc = aggregate_factory(config=config)
    assert acc(submissions=[], token={}, ci_url=None) == []


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_with_test_issues(
    aggregate_factory: Any, config: dict, submission_mock: Any, mocker: MockerFixture
) -> None:
    """Test with a valid submission."""
    config["test_issues"] = {"AAAAAAA": "BBBBBBBBB:CCCCCCCC"}
    acc = aggregate_factory(product="product", config=config)
    sub = submission_mock(product="BBBBBBBBB", version="CCCCCCCC", arch="ciao")
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    res = acc(submissions=[sub], token={}, ci_url=None)
    assert len(res) == 1


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_pc_pint(aggregate_factory: Any, config: dict, mocker: MockerFixture) -> None:
    """Test with setting PUBLIC_CLOUD_PINT_QUERY to call apply_publiccloud_pint_image."""
    acc = aggregate_factory(settings={"PUBLIC_CLOUD_PINT_QUERY": None}, config=config)
    mocker.patch(
        "openqabot.types.aggregate.apply_publiccloud_pint_image",
        return_value={"PUBLIC_CLOUD_IMAGE_ID": "Hola", "PUBLIC_CLOUD_TOOLS_IMAGE_BASE": "Base"},
    )
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    acc(submissions=[], token={}, ci_url=None)


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_pc_pint_with_submissions(
    aggregate_factory: Any, config: dict, submission_mock: Any, mocker: MockerFixture
) -> None:
    """Test with submission and setting PUBLIC_CLOUD_PINT_QUERY to call apply_publiccloud_pint_image."""
    config["test_issues"] = {"AAAAAAA": "BBBBBBBBB:CCCCCCCC"}
    acc = aggregate_factory(product="product", settings={"PUBLIC_CLOUD_PINT_QUERY": None}, config=config)
    mocker.patch(
        "openqabot.types.aggregate.apply_publiccloud_pint_image",
        return_value={"PUBLIC_CLOUD_IMAGE_ID": "Hola", "PUBLIC_CLOUD_TOOLS_IMAGE_BASE": "Base"},
    )
    sub = submission_mock(product="BBBBBBBBB", version="CCCCCCCC", arch="ciao")
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    ret = acc(submissions=[sub], token={}, ci_url=None)
    assert ret[0]["openqa"]["PUBLIC_CLOUD_IMAGE_ID"] == "Hola"


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_no_job_settings(
    aggregate_factory: Any, config: dict, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """Test with no job settings found."""
    caplog.set_level(10)  # DEBUG
    acc = aggregate_factory(product="product", config=config)
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[])
    res = acc(submissions=[], token={}, ci_url=None)
    assert res == []
    assert "No aggregate jobs found for <Aggregate product: product> on arch ciao" in caplog.text


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_pc_tools_fail(
    aggregate_factory: Any, config: dict, submission_mock: Any, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """Test with pc tools image fetch failure."""
    caplog.set_level(logging.INFO)
    config["test_issues"] = {"I": "P:V"}
    acc = aggregate_factory(product="product", settings={"PUBLIC_CLOUD_TOOLS_IMAGE_QUERY": "query"}, config=config)
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    mocker.patch("openqabot.types.aggregate.apply_pc_tools_image", return_value=None)

    sub = submission_mock(product="P", version="V", arch="ciao")
    sub.id = "I"
    res = acc(submissions=[sub], token={}, ci_url=None)
    assert res == []
    assert "No tools image found for <Aggregate product: product>" in caplog.text


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_pc_pint_fail(
    aggregate_factory: Any, config: dict, submission_mock: Any, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    """Test with pc pint image fetch failure."""
    caplog.set_level(logging.INFO)
    config["test_issues"] = {"I": "P:V"}
    acc = aggregate_factory(product="product", settings={"PUBLIC_CLOUD_PINT_QUERY": "query"}, config=config)
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    mocker.patch("openqabot.types.aggregate.apply_publiccloud_pint_image", return_value=None)

    sub = submission_mock(product="P", version="V", arch="ciao")
    sub.id = "I"
    res = acc(submissions=[sub], token={}, ci_url=None)
    assert res == []
    assert "No PINT image found for <Aggregate product: product>" in caplog.text


def test_get_buildnr_same_build() -> None:
    today = datetime.datetime.now(tz=UTC).date().strftime("%Y%m%d")
    with pytest.raises(SameBuildExistsError):
        Aggregate.get_buildnr("hash", "hash", today + "-1")


def test_filter_submissions_embargoed(
    aggregate_factory: Any, submission_mock: Any, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    acc = aggregate_factory("product")
    acc.filter_embargoed = lambda _x: True
    sub = submission_mock(embargoed=True)
    res = acc.filter_submissions([sub])
    assert res == []
    assert "skipped: Embargoed" in caplog.text


def test_filter_submissions_staging(aggregate_factory: Any, submission_mock: Any) -> None:
    acc = aggregate_factory("product")
    sub = submission_mock(staging=True)
    res = acc.filter_submissions([sub])
    assert res == []


def test_get_test_submissions_repos_existing(aggregate_factory: Any, submission_mock: Any) -> None:
    acc = aggregate_factory("product", config={"FLAVOR": "None", "archs": ["A"], "test_issues": {"ISSUES_1": "P:V"}})
    sub = submission_mock(product="P", version="V", arch="A")
    sub.id = "I"
    sub_mismatch = submission_mock(product="Other", version="V", arch="A")
    acc.get_test_submissions_and_repos([sub, sub_mismatch], "A")
    res_sub, res_repos = acc.get_test_submissions_and_repos([sub], "A")
    assert "ISSUES_1" in res_sub
    assert "REPOS_1" in res_repos


@pytest.mark.usefixtures("request_mock")
def test_aggregate_call_ci_url(aggregate_factory: Any, submission_mock: Any, mocker: MockerFixture) -> None:
    acc = aggregate_factory("product", config={"FLAVOR": "None", "archs": ["A"], "test_issues": {"I": "P:V"}})
    mocker.patch("openqabot.types.aggregate.merge_repohash", return_value="hash")
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"build": "20220101-1", "repohash": "old"}])

    sub = submission_mock(product="P", version="V", arch="A")
    sub.id = "I"
    res = acc([sub], {}, ci_url="http://ci")
    assert len(res) == 1
    assert res[0]["openqa"]["__CI_JOB_URL"] == "http://ci"


@pytest.mark.usefixtures("request_mock")
def test_process_arch_json_error(
    aggregate_factory: Any, config: dict, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    acc = aggregate_factory("product", config=config)
    mocker.patch("openqabot.types.aggregate.get_json", side_effect=requests.JSONDecodeError("msg", "doc", 0))
    assert acc(submissions=[], token={}, ci_url=None) == []
    assert "Invalid JSON received for aggregate jobs" in caplog.text


@pytest.mark.usefixtures("request_mock")
def test_process_arch_request_error(
    aggregate_factory: Any, config: dict, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    acc = aggregate_factory("product", config=config)
    mocker.patch("openqabot.types.aggregate.get_json", side_effect=requests.RequestException("error"))
    assert acc(submissions=[], token={}, ci_url=None) == []
    assert "Could not fetch previous aggregate jobs" in caplog.text


def test_process_arch_onetime_skip(aggregate_factory: Any, config: dict, mocker: MockerFixture) -> None:
    acc = aggregate_factory("product", config=config)
    acc.onetime = True
    mocker.patch("openqabot.types.aggregate.merge_repohash", return_value="new")
    today = datetime.datetime.now(tz=UTC).date().strftime("%Y%m%d")
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"build": today + "-1", "repohash": "old"}])
    assert acc.process_arch("ciao", [], {}, None, ignore_onetime=False) is None


def test_aggregate_call_deprioritize_limit(aggregate_factory: Any, submission_mock: Any, mocker: MockerFixture) -> None:
    acc = aggregate_factory("product", config={"FLAVOR": "None", "archs": ["A"], "test_issues": {"I": "P:V"}})
    mocker.patch("openqabot.config.settings.deprioritize_limit", 10)
    mocker.patch("openqabot.types.aggregate.merge_repohash", return_value="hash")
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"build": "old", "repohash": "old"}])

    sub = submission_mock(product="P", version="V", arch="A")
    sub.id = "I"
    res = acc([sub], {}, ci_url=None)
    assert res[0]["openqa"]["_DEPRIORITIZE_LIMIT"] == 10


def test_aggregate_call_pc_tools_success(aggregate_factory: Any, submission_mock: Any, mocker: MockerFixture) -> None:
    config = {"FLAVOR": "None", "archs": ["A"], "test_issues": {"I": "P:V"}}
    acc = aggregate_factory("product", settings={"PUBLIC_CLOUD_TOOLS_IMAGE_QUERY": "query"}, config=config)
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"repohash": "old", "build": "old"}])
    mocker.patch(
        "openqabot.types.aggregate.apply_pc_tools_image", return_value={"PUBLIC_CLOUD_TOOLS_IMAGE_BASE": "Base"}
    )
    sub = submission_mock(product="P", version="V", arch="A")
    sub.id = "I"
    res = acc([sub], {}, ci_url=None)
    assert len(res) == 1
    assert res[0]["openqa"]["PUBLIC_CLOUD_TOOLS_IMAGE_BASE"] == "Base"


def test_aggregate_priority(aggregate_factory: Any, submission_mock: Any, mocker: MockerFixture) -> None:
    acc = aggregate_factory("product", config={"FLAVOR": "None", "archs": ["A"], "test_issues": {"I": "P:V"}})
    mocker.patch("openqabot.types.aggregate.merge_repohash", return_value="hash")
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"build": "old", "repohash": "old"}])

    sub = submission_mock(product="P", version="V", arch="A")
    sub.priority = 100
    res = acc([sub], {}, ci_url=None)
    assert res[0]["openqa"]["_PRIORITY"] == 45


def test_aggregate_multiple_priority(aggregate_factory: Any, submission_mock: Any, mocker: MockerFixture) -> None:
    acc = aggregate_factory(
        "product", config={"FLAVOR": "None", "archs": ["A"], "test_issues": {"I1": "P:V", "I2": "P:V"}}
    )
    mocker.patch("openqabot.types.aggregate.merge_repohash", return_value="hash")
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"build": "old", "repohash": "old"}])

    sub1 = submission_mock(product="P", version="V", arch="A")
    sub1.id = 1
    sub1.priority = 100
    sub2 = submission_mock(product="P", version="V", arch="A")
    sub2.id = 2
    sub2.priority = 200
    res = acc([sub1, sub2], {}, ci_url=None)
    assert res[0]["openqa"]["_PRIORITY"] == 40


def test_process_arch_same_build_exists(
    aggregate_factory: Any, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    config = {"FLAVOR": "None", "archs": ["A"], "test_issues": {"I": "P:V"}}
    acc = aggregate_factory("product", config=config)
    mocker.patch("openqabot.types.aggregate.merge_repohash", return_value="same")
    today = datetime.datetime.now(tz=UTC).date().strftime("%Y%m%d")
    mocker.patch("openqabot.types.aggregate.get_json", return_value=[{"build": today + "-1", "repohash": "same"}])
    assert acc.process_arch("A", [], {}, None, ignore_onetime=False) is None
    assert "A build with the same RepoHash already exists" in caplog.text


def test_aggregate_duplicate_submissions(aggregate_factory: Any, submission_mock: Any) -> None:
    agg = aggregate_factory(
        product="SLES",
        settings={"VERSION": "15-SP3", "DISTRI": "sles"},
        config={"FLAVOR": "AAA", "archs": ["x86_64"], "test_issues": {"ISSUE": "product:version"}},
    )

    sub1 = submission_mock()
    sub1.id = 123
    sub2 = submission_mock()
    sub2.id = 123

    test_submissions = defaultdict(list)
    test_submissions["ISSUE"] = [sub1, sub2]
    test_repos = defaultdict(list)
    test_repos["REPOS"] = ["repo"]

    post_data = PostData(test_submissions, test_repos, "hash", "build")
    res = agg.create_full_post("x86_64", post_data, None)

    assert res is not None
    assert len(res["qem"]["incidents"]) == 1
    assert res["qem"]["incidents"][0] == 123


def test_aggregate_url_format(aggregate_factory: Any, mocker: MockerFixture) -> None:
    config = {"FLAVOR": "AAA", "archs": ["x86_64"], "test_issues": {"ISSUE": "product:version"}}
    agg = aggregate_factory(
        product="SLES",
        settings={"VERSION": "15-SP3", "DISTRI": "sles"},
        config=config,
    )
    sub = mocker.MagicMock(spec=Submission)
    sub.id = 42
    sub.type = "smelt"
    sub.livepatch = False
    sub.staging = False
    sub.embargoed = False
    sub.priority = None
    sub.__str__.side_effect = lambda: f"{sub.type}:{sub.id}"
    sub.channels = [Repos("product", "version", "x86_64")]

    _, test_repos = agg.get_test_submissions_and_repos([sub], "x86_64")
    repo_url = test_repos["ISSUE"][0]

    assert "smelt:" not in repo_url
    assert "/42/" in repo_url

    test_submissions = defaultdict(list)
    test_submissions["ISSUE"] = [sub]
    test_repos = defaultdict(list)
    test_repos["REPOS"] = [repo_url]
    post_data = PostData(test_submissions, test_repos, "hash", "build")

    res = agg.create_full_post("x86_64", post_data, None)

    assert res is not None
    dashboard_url = res["openqa"]["__DASHBOARD_INCIDENTS_URL"]
    assert "?type=" not in dashboard_url
    assert "/incident/42" in dashboard_url
    assert "smelt" not in dashboard_url  # Should be clean of type if it's the default
