# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test increment approver scenarios to make sure that two products not interfer with each other."""


from argparse import Namespace
import logging
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import urlparse

import pytest
from pytest_mock import MockerFixture

import responses
from openqabot.incrementapprover import IncrementApprover
from openqabot.loader.incrementconfig import IncrementConfig
from openqabot.config import BUILD_REGEX

from .helpers import (fake_get_request_list, fake_osc_get_config, fake_request_openqa_job_results)


@responses.activate
@pytest.mark.usefixtures("fake_product_repo", "fakeget_package_diff")
def test_scheduling_extra_livepatching_builds_based_on_source_report(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mock_post_job = MagicMock()
    mocker.patch("openqabot.openqa.OpenQAInterface.post_job", new=mock_post_job)
    mocker.patch("osc.core.get_request_list", side_effect=fake_get_request_list)
    mocker.patch("osc.conf.get_config", side_effect=fake_osc_get_config)
    mocker.patch("openqabot.incrementapprover.IncrementApprover.request_openqa_job_results", side_effect=fake_request_openqa_job_results)
    caplog.set_level(logging.DEBUG, logger="bot.increment_approver")
    caplog.set_level(logging.DEBUG, logger="bot.requests")
    caplog.set_level(logging.DEBUG, logger="bot.loader.buildinfo")

    args = Namespace(
        dry=False,
        token="not-secret",
        openqa_instance=urlparse("http://openqa-instance"),
        accepted=True,
        request_id=None,
        project_base="OBS:PROJECT",
        build_project_suffix="TEST",
        diff_project_suffix="diff_project_suffix",
        distri="sle",
        version="16.0",
        flavor="Online-Increments",
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

    increment_approver = IncrementApprover(args)
    increment_approver.config = list(IncrementConfig.from_config_path(Path("tests/fixtures/ambiguos/")))
    increment_approver()
    jobs = [call_args.args[0] for call_args in mock_post_job.call_args_list]
    print(jobs)
