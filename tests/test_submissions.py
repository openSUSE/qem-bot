# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from openqabot.types.baseconf import JobConfig
from openqabot.types.submissions import Submissions
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
