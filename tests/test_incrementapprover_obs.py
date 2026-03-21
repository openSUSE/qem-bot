# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test increment approver OBS."""

from __future__ import annotations

import logging
from argparse import Namespace
from typing import TYPE_CHECKING
from unittest.mock import patch
from urllib.parse import urlparse

import osc.core
import pytest

import responses
from openqabot.config import BUILD_REGEX, OBS_GROUP, settings
from openqabot.incrementapprover import IncrementApprover
from openqabot.requests import find_request_on_obs, get_obs_request_list
from openqabot.types.increment import ApprovalStatus

from .helpers import (
    ReviewState,
    fake_get_request_list,
    fake_osc_get_config,
    prepare_approver,
    run_approver,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@responses.activate
@pytest.mark.usefixtures("fake_product_repo")
def test_specified_obs_request_not_found_skips_approval(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    def fake_request_from_api(apiurl: str, reqid: int) -> None:
        assert apiurl == settings.obs_url
        assert reqid == 43

    mocker.patch("osc.core.Request.from_api", side_effect=fake_request_from_api)
    run_approver(mocker, caplog, request_id=43)
    assert "Checking specified request 43" in caplog.messages
    assert "Skipping approval: OBS:PROJECT:TEST: No relevant requests in states new/review/accepted" in caplog.messages


@responses.activate
@pytest.mark.usefixtures("fake_product_repo")
def test_specified_obs_request_found_renders_request(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    def fake_request_from_api(apiurl: str, reqid: int) -> osc.core.Request:
        assert apiurl == settings.obs_url
        assert reqid == 43
        req = mocker.Mock(spec=osc.core.Request)
        req.reqid = 43
        req.state = mocker.Mock()
        req.state.to_xml.return_value = True
        req.reviews = [ReviewState("review", OBS_GROUP)]
        req.to_str.return_value = "<request />"
        return req

    mocker.patch("osc.core.Request.from_api", side_effect=fake_request_from_api)
    approver = prepare_approver(caplog, request_id=43)
    find_request_on_obs(approver.args, "foo")
    assert "Checking specified request 43" in caplog.text
    assert "<request />" in caplog.text


@responses.activate
@pytest.mark.usefixtures("fake_product_repo")
def testfind_request_on_obs_with_request_id(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    def fake_request_from_api(apiurl: str, reqid: int) -> osc.core.Request:
        assert apiurl == settings.obs_url
        assert reqid == 43
        req = mocker.Mock(spec=osc.core.Request)
        req.reqid = 43
        req.state = mocker.Mock()
        req.state.to_xml.return_value = True
        req.reviews = [ReviewState("review", OBS_GROUP)]
        req.to_str.return_value = "<request />"
        return req

    mocker.patch("osc.core.Request.from_api", side_effect=fake_request_from_api)
    approver = prepare_approver(caplog, request_id=43)
    find_request_on_obs(approver.args, "foo")
    assert "Checking specified request 43" in caplog.text
    assert "<request />" in caplog.text


@responses.activate
@pytest.mark.usefixtures("fake_product_repo")
def testfind_request_on_obs_caching(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mock_get_requests = mocker.patch("osc.core.get_request_list", side_effect=fake_get_request_list)
    mocker.patch("osc.conf.get_config", side_effect=fake_osc_get_config)

    approver = prepare_approver(caplog)

    res1 = find_request_on_obs(approver.args, "OBS:PROJECT:TEST")
    assert mock_get_requests.call_count == 1
    assert res1
    assert res1.reqid == 42

    res2 = find_request_on_obs(approver.args, "OBS:PROJECT:TEST")
    assert mock_get_requests.call_count == 1
    assert res1 == res2

    mock_get_requests.return_value = []
    get_obs_request_list.cache_clear()
    find_request_on_obs(approver.args, "OBS:PROJECT:OTHER")
    assert mock_get_requests.call_count == 2


def testhandle_approval_dry(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.INFO)
    args = Namespace(
        dry=True,
        token="token",
        gitea_token=None,
        openqa_instance=urlparse("http://instance.qa"),
        accepted=True,
        request_id=None,
        project_base="BASE",
        build_project_suffix="TEST",
        diff_project_suffix="none",
        distri="sle",
        version="any",
        flavor="any",
        schedule=False,
        reschedule=False,
        build_listing_sub_path="product",
        build_regex=BUILD_REGEX,
        product_regex=".*",
        fake_data=True,
        increment_config=None,
        packages=[],
        archs=set(),
        settings={},
        additional_builds=[],
    )
    with patch("osc.conf.get_config"), patch("openqabot.config.settings.obs_url", "https://api.suse.de"):
        approver = IncrementApprover(args)
        req = mocker.Mock(spec=osc.core.Request)
        req.reqid = 123
        status = ApprovalStatus(req, ok_jobs={1}, reasons_to_disapprove=[], processed_jobs=set(), builds=set(), jobs=[])
        mock_osc_change = mocker.patch("osc.core.change_review_state")

        approver.handle_approval(status)
        mock_osc_change.assert_not_called()
        assert (
            "Approving OBS request https://build.suse.de/request/show/123: All 1 openQA jobs have passed/softfailed"
            in caplog.text
        )


def testapprove_on_obs_dry(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    approver.args.dry = True
    mock_osc_change = mocker.patch("osc.core.change_review_state")
    approver.approve_on_obs("123", "msg")
    mock_osc_change.assert_not_called()


def testhandle_approval_no_jobs_safeguard(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    req = mocker.Mock(spec=osc.core.Request)
    req.reqid = 123
    status = ApprovalStatus(req, ok_jobs=set(), reasons_to_disapprove=[], processed_jobs=set(), builds=set(), jobs=[])

    approver.handle_approval(status)
    assert "No openQA jobs were found/checked for this request." in caplog.text
    assert "Not approving OBS request https://build.suse.de/request/show/123 for the following reasons:" in caplog.text


@responses.activate
@pytest.mark.usefixtures("fake_product_repo")
def testfind_request_on_obs_not_accepted(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    approver = prepare_approver(caplog)
    approver.args.accepted = False
    mock_get_list = mocker.patch("openqabot.requests.get_obs_request_list", return_value=[])
    find_request_on_obs(approver.args, "project")
    assert mock_get_list.call_args[0][1] == ("new", "review")
