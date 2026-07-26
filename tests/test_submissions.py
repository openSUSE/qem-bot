# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test Submissions."""

import pytest

from openqabot.types.baseconf import JobConfig
from openqabot.types.submissions import Submissions
from openqabot.types.types import Repos

from .fixtures.submissions import MockSubmission


def _make_submissions(flavor_config: dict, product: str = "SLE") -> Submissions:
    return Submissions(
        JobConfig(product, None, None, {}, {"FLAVOR": flavor_config}),
        extrasettings=set(),
    )


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


@pytest.mark.parametrize(
    ("flavor_config", "expected_warnings"),
    [
        pytest.param({"AAA": {"archs": ["x86_64"], "excluded_packages": ["foo"]}}, [], id="all-known-keys"),
        pytest.param(
            {"AAA": {"archs": ["x86_64"], "excluded_package": ["foo"]}}, ["excluded_package"], id="typo-blocklist"
        ),
        pytest.param({"AAA": {"archs": ["x86_64"], "bogus": 1, "typo": 2}}, ["bogus", "typo"], id="multiple-unknown"),
        pytest.param({}, [], id="no-flavors"),
    ],
)
def test_warn_unknown_flavor_keys(
    caplog: pytest.LogCaptureFixture, flavor_config: dict, expected_warnings: list[str]
) -> None:
    """Unknown per-flavor keys are warned about so a misspelled blocklist is not silently ignored."""
    with caplog.at_level("WARNING", logger="bot.types.submissions"):
        _make_submissions(flavor_config)
    warned = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert len(warned) == len(expected_warnings)
    for key in expected_warnings:
        assert any(repr(key) in msg for msg in warned)
