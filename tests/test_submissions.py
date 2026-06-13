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


@pytest.mark.parametrize(
    ("existing_flavor", "existing_rev", "new_rev", "cooldown", "expected"),
    [
        (None, None, 2000, 7200, False),  # No existing jobs
        ("flavor", 2000, 2000, 7200, True),  # Exact match
        ("flavor", 2001, 2000, 7200, True),  # Older match
        ("flavor", 1000, 2000, 7200, True),  # Within cooldown
        ("flavor", 1000, 9000, 7200, False),  # Outside cooldown
        ("flavor", 1000, 2000, 500, False),  # Configurable cooldown - trigger
        ("flavor", 1000, 2000, 1500, True),  # Configurable cooldown - skip
        ("other", 2000, 2000, 7200, False),  # Different flavor
    ],
)
def test_is_scheduled_job_scenarios(
    mocker: Any,
    sub_context: SubContext,
    existing_flavor: str | None,
    existing_rev: int | None,
    new_rev: int,
    cooldown: int,
    *,
    expected: bool,
) -> None:
    """Test various scheduling and cooldown scenarios."""
    jobs = (
        [{"flavor": existing_flavor, "arch": "x86_64", "version": "15-SP3", "settings": {"REPOHASH": existing_rev}}]
        if existing_flavor
        else []
    )
    mocker.patch("openqabot.types.submissions.Submissions._get_scheduled_jobs", return_value=jobs)
    mocker.patch.object(settings, "schedule_cooldown", cooldown)
    cast("MagicMock", sub_context.sub.revisions_with_fallback).return_value = new_rev

    assert Submissions.is_scheduled_job(sub_context, "15-SP3") is expected
