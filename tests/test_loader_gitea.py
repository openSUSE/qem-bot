# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import json
import logging
import urllib.error
from io import BytesIO
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
import requests
from pytest_mock import MockerFixture

from openqabot.loader import gitea


def test_post_json_on_not_ok_logs_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger="bot.loader.gitea")
    mocked_post = mocker.Mock()
    mocked_post.ok = False
    mocker.patch("openqabot.loader.gitea.retried_requests.post", return_value=mocked_post)
    gitea.post_json("foo", {}, {}, host="my.host")
    assert "Gitea API error: POST to my.host/api/v1/foo" in caplog.text


def test_get_open_prs_returns_empty_on_dry_run(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.read_json", return_value=42)
    assert gitea.get_open_prs({}, "repo", dry=True, number=None) == 42


def test_get_open_prs_returns_specified_pr(mocker: MockerFixture) -> None:
    mocked_get_json = mocker.patch("openqabot.loader.gitea.get_json", return_value=42)
    assert gitea.get_open_prs({"Authorization": "token my_token"}, "my_repo", dry=False, number=1) == [42]
    mocked_get_json.assert_called_once_with("repos/my_repo/pulls/1", {"Authorization": "token my_token"})


def test_get_open_prs_metadata_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.get_json", side_effect=requests.RequestException("error"))
    res = gitea.get_open_prs({}, "repo", dry=False, number=124)
    assert res == []
    assert "PR git:124 ignored: Could not read PR metadata" in caplog.text


def test_get_open_prs_iter_pages(mocker: MockerFixture) -> None:
    # return 2 pages then empty
    mocker.patch("openqabot.loader.gitea.get_json", side_effect=[[1], [2], []])
    res = gitea.get_open_prs({}, "repo", dry=False, number=None)
    assert res == [1, 2]


def test_get_open_prs_json_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.get_json", side_effect=requests.exceptions.JSONDecodeError("msg", "doc", 0))
    res = gitea.get_open_prs({}, "repo", dry=False, number=None)
    assert res == []
    assert "Gitea API error: Invalid JSON received for open PRs" in caplog.text


def test_get_open_prs_request_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.get_json", side_effect=requests.exceptions.RequestException("error"))
    res = gitea.get_open_prs({}, "repo", dry=False, number=None)
    assert res == []
    assert "Gitea API error: Could not fetch open PRs" in caplog.text


def test_get_product_version_from_repo_listing_json_error(mocker: MockerFixture) -> None:
    mock_log = mocker.patch("openqabot.loader.gitea.log")
    mock_response = MagicMock()
    mock_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
    mocker.patch.object(gitea.retried_requests, "get", return_value=mock_response)

    res = gitea.get_product_version_from_repo_listing("project", "product", "repo")
    assert res == ""
    assert mock_log.info.called


def test_get_product_version_from_repo_listing_http_error(mocker: MockerFixture) -> None:
    gitea.get_product_version_from_repo_listing.cache_clear()
    mock_log = mocker.patch("openqabot.loader.gitea.log")
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("error")
    mocker.patch.object(gitea.retried_requests, "get", return_value=mock_response)

    res = gitea.get_product_version_from_repo_listing("project", "product", "repo")
    assert res == ""
    assert mock_log.warning.called


def test_get_product_version_from_repo_listing_request_exception(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    gitea.get_product_version_from_repo_listing.cache_clear()
    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.retried_requests.get", side_effect=requests.RequestException("error"))
    res = gitea.get_product_version_from_repo_listing("project", "product", "repo")
    assert res == ""
    assert "Product version unresolved" in caplog.text


def test_determine_relevant_archs_from_multibuild_info_success(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="prod")
    mocker.patch("openqabot.loader.gitea.read_utf8", return_value="xml")
    mocker.patch("openqabot.loader.gitea.MultibuildFlavorResolver.parse_multibuild_data", return_value=["prod_x86_64"])
    mocker.patch("openqabot.loader.gitea.ARCHS", ["x86_64"])
    res = gitea.determine_relevant_archs_from_multibuild_info("project", dry=True)
    assert res is not None
    assert "x86_64" in res


def test_make_submission_from_gitea_pr_dry(mocker: MockerFixture) -> None:
    pr = {"number": 124, "state": "open", "url": "url", "base": {"repo": {"full_name": "owner/repo", "name": "repo"}}}
    mocker.patch("openqabot.loader.gitea.read_json", return_value=[])

    def mock_add_comments(incident: dict, _comments: list, *, dry: bool) -> None:  # noqa: ARG001
        incident["channels"] = [1]

    mocker.patch("openqabot.loader.gitea.add_comments_and_referenced_build_results", side_effect=mock_add_comments)

    def mock_add_packages(incident: dict, _token: dict, _files: list, *, dry: bool) -> None:  # noqa: ARG001
        incident["packages"] = ["pkg"]

    mocker.patch("openqabot.loader.gitea.add_packages_from_files", side_effect=mock_add_packages)

    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=False, only_requested_prs=False, dry=True)
    assert res is not None


def test_make_submission_from_gitea_pr_skips(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    pr = {"number": 123, "state": "open", "url": "url", "base": {"repo": {"full_name": "owner/repo", "name": "repo"}}}
    mocker.patch("openqabot.loader.gitea.get_json", return_value=[])

    # Skip due to no channels
    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=False, only_requested_prs=False, dry=False)
    assert res is None
    assert "PR git:123 skipped: No channels found" in caplog.text

    # Skip due to build not acceptable
    caplog.clear()
    mocker.patch("openqabot.loader.gitea.is_build_acceptable_and_log_if_not", return_value=False)

    def mock_add_comments(incident: dict, _comments: list, *, dry: bool) -> None:  # noqa: ARG001
        incident["channels"] = [1]

    mocker.patch("openqabot.loader.gitea.add_comments_and_referenced_build_results", side_effect=mock_add_comments)
    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=True, only_requested_prs=False, dry=False)
    assert res is None

    # Skip due to no packages
    caplog.clear()
    mocker.patch("openqabot.loader.gitea.is_build_acceptable_and_log_if_not", return_value=True)
    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=False, only_requested_prs=False, dry=False)
    assert res is None
    assert "PR git:123 skipped: No packages found" in caplog.text


def test_add_build_result_inconsistent_scminfo(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    incident = {"scminfo": "old", "number": 1}
    res = mocker.Mock()
    res.get.return_value = "project"
    res.findall.return_value = [mocker.Mock(text="new")]

    mocker.patch("openqabot.loader.gitea.add_channel_for_build_result")

    gitea.add_build_result(incident, res, set(), set(), set(), set())

    assert "PR git:1: Inconsistent SCM info for project project: found 'new' vs 'old'" in caplog.text


def test_determine_relevant_archs_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="prod")
    mocker.patch("openqabot.loader.gitea.get_multibuild_data", side_effect=Exception("oops"))

    res = gitea.determine_relevant_archs_from_multibuild_info("project", dry=False)

    assert res is None
    assert "Could not determine relevant architectures for project: oops" in caplog.text


def test_is_build_result_relevant_repo_mismatch(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.OBS_REPO_TYPE", "match")
    res = {"repository": "mismatch", "arch": "x86_64"}
    assert not gitea.is_build_result_relevant(res, {"x86_64"})


def test_add_build_results_url_mismatch_just_passes() -> None:
    gitea.add_build_results({}, ["http://nomatch.com"], dry=True)


def test_add_packages_from_patchinfo_non_dry(mocker: MockerFixture) -> None:
    mock_get = mocker.patch("openqabot.loader.gitea.retried_requests.get")
    mock_get.return_value.text = "<patchinfo><package>pkg1</package></patchinfo>"

    incident = {"packages": []}
    gitea.add_packages_from_patchinfo(incident, {}, "url", dry=False)

    assert incident["packages"] == ["pkg1"]


def test_make_submission_from_gitea_pr_dry_other_number_passes(mocker: MockerFixture) -> None:
    pr = {"number": 999, "state": "open", "url": "url", "base": {"repo": {"full_name": "owner/repo", "name": "repo"}}}

    mocker.patch("openqabot.loader.gitea.add_reviews", return_value=1)

    def mock_add_chan(inc: dict, *_: Any, **__: Any) -> None:
        inc["channels"].append("chan")

    mocker.patch("openqabot.loader.gitea.add_comments_and_referenced_build_results", side_effect=mock_add_chan)

    def mock_add_pkg(inc: dict, *_: Any, **__: Any) -> None:
        inc["packages"].append("pkg")

    mocker.patch("openqabot.loader.gitea.add_packages_from_files", side_effect=mock_add_pkg)

    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=False, only_requested_prs=False, dry=True)

    assert res is not None
    assert res["number"] == 999


def test_determine_relevant_archs_empty_product(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="")
    assert gitea.determine_relevant_archs_from_multibuild_info("project", dry=False) is None


def test_add_build_results_http_error(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.determine_relevant_archs_from_multibuild_info", return_value=None)
    err = urllib.error.HTTPError("url", 404, "msg", cast("Any", {}), None)
    mocker.patch("openqabot.loader.gitea.http_GET", side_effect=err)

    incident = {"number": 123}
    gitea.add_build_results(incident, ["http://obs/project/show/proj"], dry=False)

    assert "Build results for project proj unreadable, skipping" in caplog.text
    assert "proj" in cast("list", incident["failed_or_unpublished_packages"])


def test_is_build_result_relevant_arch_filter(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.OBS_REPO_TYPE", None)
    res = {"arch": "s390x"}
    assert not gitea.is_build_result_relevant(res, {"x86_64"})
    assert gitea.is_build_result_relevant(res, {"s390x"})


def test_add_build_result_published(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="SLES")
    mocker.patch("openqabot.loader.gitea.OBS_PRODUCTS", ["SLES"])
    mocker.patch("openqabot.loader.gitea.add_channel_for_build_result", return_value="chan")

    incident = {}
    res = mocker.Mock()
    res.findall.return_value = []
    res.get.side_effect = lambda k: "other" if k == "state" else "val"

    unpublished = set()
    gitea.add_build_result(incident, res, set(), set(), unpublished, set())
    assert "chan" in unpublished

    mocker.patch("openqabot.loader.gitea.OBS_PRODUCTS", ["all"])
    unpublished.clear()
    gitea.add_build_result(incident, res, set(), set(), unpublished, set())
    assert "chan" in unpublished


def test_make_submission_from_gitea_pr_no_reviews(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    pr = {"number": 123, "state": "open", "url": "url", "base": {"repo": {"full_name": "owner/repo", "name": "repo"}}}
    mocker.patch("openqabot.loader.gitea.get_json", return_value=[])
    mocker.patch("openqabot.loader.gitea.add_reviews", return_value=0)
    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=False, only_requested_prs=True, dry=False)
    assert res is None
    assert "PR git:123 skipped: No reviews by" in caplog.text


def test_add_build_results_failed_packages(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.determine_relevant_archs_from_multibuild_info", return_value=None)
    mocker.patch("openqabot.loader.gitea.OBS_REPO_TYPE", None)
    xml_data = """
    <buildresults>
        <result project="proj" repository="repo" arch="x86_64" state="published">
            <status package="pkg1" code="failed"/>
        </result>
    </buildresults>
    """
    mocker.patch("openqabot.loader.gitea.http_GET", return_value=BytesIO(xml_data.encode()))
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="SLES")
    mocker.patch("openqabot.loader.gitea.OBS_PRODUCTS", ["SLES"])
    incident = {"number": 123}
    gitea.add_build_results(incident, ["http://obs/project/show/proj"], dry=False)
    assert "PR git:123: Some packages failed: pkg1" in caplog.text
    assert "pkg1" in cast("list", incident["failed_or_unpublished_packages"])


def test_is_build_acceptable_fail(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    incident = {"failed_or_unpublished_packages": ["pkg1"], "successful_packages": ["pkg2"]}
    assert not gitea.is_build_acceptable_and_log_if_not(incident, 123)
    assert "Skipping PR git:123: Not all packages succeeded or published" in caplog.text


def test_is_build_result_relevant_repo_match(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.OBS_REPO_TYPE", "standard")
    res = {"repository": "standard", "arch": "x86_64"}
    assert gitea.is_build_result_relevant(res, {"x86_64"})


def test_add_build_results_dry_124(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.determine_relevant_archs_from_multibuild_info", return_value=None)
    mock_read_xml = mocker.patch("openqabot.loader.gitea.read_xml")
    mock_read_xml.return_value.getroot.return_value.findall.return_value = []
    incident = {"number": 124}
    gitea.add_build_results(incident, ["http://obs/project/show/proj"], dry=True)
    mock_read_xml.assert_called_once_with("build-results-124-proj")


def test_make_submission_from_gitea_pr_exception(caplog: pytest.LogCaptureFixture) -> None:
    pr = {"number": 123}  # Missing base/repo
    res = gitea.make_submission_from_gitea_pr(pr, {}, only_successful_builds=False, only_requested_prs=False, dry=False)
    assert res is None
    assert "Gitea API error: Unable to process PR git:123" in caplog.text


def test_is_build_acceptable_success() -> None:
    incident = {"failed_or_unpublished_packages": [], "successful_packages": ["pkg1"]}
    assert gitea.is_build_acceptable_and_log_if_not(incident, 123)


def test_get_multibuild_data(mocker: MockerFixture) -> None:
    mock_resolver = mocker.patch("openqabot.loader.gitea.MultibuildFlavorResolver")
    mock_resolver.return_value.get_multibuild_data.return_value = "data"

    assert gitea.get_multibuild_data("proj") == "data"
    mock_resolver.assert_called_with(gitea.OBS_URL, "proj", "000productcompose")
