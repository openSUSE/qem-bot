# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test Submissions."""

from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from openqabot.config import settings
from openqabot.types.baseconf import JobConfig
from openqabot.types.submissions import SubContext, Submissions
from openqabot.types.types import Repos

from .fixtures.submissions import MockSubmission


def test_submissions_constructor() -> None:
    """Test for the bare minimal set of arguments needed by the constructor."""
    test_config = {}
    test_config["FLAVOR"] = {}
    Submissions(
        JobConfig(
            product="",
            product_repo=None,
            product_version=None,
            settings={},
            config=test_config,
        ),
        extrasettings=set(),
    )


def test_submissions_printable() -> None:
    """Try the printable."""
    test_config = {}
    test_config["FLAVOR"] = {}
    sub = Submissions(
        JobConfig(
            product="hello",
            product_repo=None,
            product_version=None,
            settings={},
            config=test_config,
        ),
        extrasettings=set(),
    )
    assert str(sub) == "<Submissions product: hello>"


def test_making_repo_url() -> None:
    s = {"VERSION": "", "DISTRI": None}
    c = {"FLAVOR": {"AAA": {"archs": [""], "issues": {"1234": ":"}}}}
    subs = Submissions(
        JobConfig(
            product="",
            product_repo=None,
            product_version=None,
            settings=s,
            config=c,
        ),
        extrasettings=set(),
    )
    sub = MockSubmission()
    sub.id = 42
    exp_repo_start = "http://%REPO_MIRROR_HOST%/ibs/SUSE:/Maintenance:/42/"
    repo = subs.make_repo_url(sub, Repos("openSUSE", "15.7", "x86_64"))
    assert repo == exp_repo_start + "SUSE_Updates_openSUSE_15.7_x86_64"
    repo = subs.make_repo_url(sub, Repos("openSUSE-SLE", "15.7", "x86_64"))
    assert repo == exp_repo_start + "SUSE_Updates_openSUSE-SLE_15.7"
    slfo_chan = Repos("SUSE:SLFO", "SUSE:SLFO:1.1.99:PullRequest:166:SLES", "x86_64", "15.99")
    repo = subs.make_repo_url(sub, slfo_chan)
    exp_repo = "http://%REPO_MIRROR_HOST%/ibs/SUSE:/SLFO:/SUSE:/SLFO:/1.1.99:/PullRequest:/166:/SLES/product/repo/SLES-15.99-x86_64/"
    assert repo == exp_repo


@pytest.fixture
def sub_context() -> SubContext:
    """Fixture for SubContext."""
    sub = MagicMock()
    sub.id = 123
    sub.revisions_with_fallback.return_value = 2000
    return SubContext(sub, "x86_64", "flavor", {"some": "data"})


def test_is_scheduled_job_no_existing_jobs(mocker: Any, sub_context: SubContext) -> None:
    """Test when no jobs are scheduled."""
    mocker.patch("openqabot.types.submissions.Submissions._get_scheduled_jobs", return_value=[])
    assert Submissions.is_scheduled_job(sub_context, "15-SP3") is False


def test_is_scheduled_job_exact_match(mocker: Any, sub_context: SubContext) -> None:
    """Test when a job with exact REPOHASH is already scheduled."""
    mocker.patch(
        "openqabot.types.submissions.Submissions._get_scheduled_jobs",
        return_value=[{"flavor": "flavor", "arch": "x86_64", "version": "15-SP3", "settings": {"REPOHASH": 2000}}],
    )
    assert Submissions.is_scheduled_job(sub_context, "15-SP3") is True


def test_is_scheduled_job_older_match(mocker: Any, sub_context: SubContext) -> None:
    """Test when a job with newer REPOHASH is already scheduled."""
    mocker.patch(
        "openqabot.types.submissions.Submissions._get_scheduled_jobs",
        return_value=[{"flavor": "flavor", "arch": "x86_64", "version": "15-SP3", "settings": {"REPOHASH": 2001}}],
    )
    assert Submissions.is_scheduled_job(sub_context, "15-SP3") is True


def test_is_scheduled_job_within_cooldown(mocker: Any, sub_context: SubContext) -> None:
    """Test when a new REPOHASH is within the cooldown period."""
    # Existing job has REPOHASH 1000. New REPOHASH is 2000.
    # Diff is 1000. Default cooldown is 7200.
    mocker.patch(
        "openqabot.types.submissions.Submissions._get_scheduled_jobs",
        return_value=[{"flavor": "flavor", "arch": "x86_64", "version": "15-SP3", "settings": {"REPOHASH": 1000}}],
    )
    assert Submissions.is_scheduled_job(sub_context, "15-SP3") is True


def test_is_scheduled_job_outside_cooldown(mocker: Any, sub_context: SubContext) -> None:
    """Test when a new REPOHASH is outside the cooldown period."""
    # Existing job has REPOHASH 1000. New REPOHASH is 9000.
    # Diff is 8000. Default cooldown is 7200.
    cast("MagicMock", sub_context.sub.revisions_with_fallback).return_value = 9000
    mocker.patch(
        "openqabot.types.submissions.Submissions._get_scheduled_jobs",
        return_value=[{"flavor": "flavor", "arch": "x86_64", "version": "15-SP3", "settings": {"REPOHASH": 1000}}],
    )
    assert Submissions.is_scheduled_job(sub_context, "15-SP3") is False


def test_is_scheduled_job_different_flavor(mocker: Any, sub_context: SubContext) -> None:
    """Test when existing jobs are for a different flavor."""
    mocker.patch(
        "openqabot.types.submissions.Submissions._get_scheduled_jobs",
        return_value=[
            {"flavor": "other_flavor", "arch": "x86_64", "version": "15-SP3", "settings": {"REPOHASH": 2000}}
        ],
    )
    assert Submissions.is_scheduled_job(sub_context, "15-SP3") is False


def test_is_scheduled_job_configurable_cooldown(mocker: Any, sub_context: SubContext) -> None:
    """Test cooldown period override via settings."""
    # Existing job has REPOHASH 1000. New REPOHASH is 2000.
    # Diff is 1000.
    mocker.patch(
        "openqabot.types.submissions.Submissions._get_scheduled_jobs",
        return_value=[{"flavor": "flavor", "arch": "x86_64", "version": "15-SP3", "settings": {"REPOHASH": 1000}}],
    )

    mocker.patch.object(settings, "schedule_cooldown", 500)
    # Diff (1000) > cooldown (500) -> Should schedule
    assert Submissions.is_scheduled_job(sub_context, "15-SP3") is False

    mocker.patch.object(settings, "schedule_cooldown", 1500)
    # Diff (1000) < cooldown (1500) -> Should NOT schedule
    assert Submissions.is_scheduled_job(sub_context, "15-SP3") is True
