# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader parent build results."""

import logging
from typing import Any, cast
from urllib.error import HTTPError, URLError

import pytest
from lxml import etree  # ty: ignore[unresolved-import]
from pytest_mock import MockerFixture

from openqabot.config import settings
from openqabot.loader import parentbuild

PARENT = "SUSE:SLFO:1.1.99:PullRequest:124"
UNKNOWN_PACKAGE = "kernel-livepatch-SLE16_Update_0"
SKIPPING_WARNING = (
    f"Skipping archs ['aarch64'] for {PARENT}: packages ['{UNKNOWN_PACKAGE}'] are excluded in the parent project"
)
UNDECIDED_WARNING = (
    f"Parent build results of {PARENT} do not report every package ['{UNKNOWN_PACKAGE}'] "
    "on archs ['x86_64'], keeping them"
)
UNSUPPORTED_WARNING = (
    f"Parent build results of {PARENT} exclude packages ['{UNKNOWN_PACKAGE}'] "
    "on every arch, keeping ['aarch64', 'x86_64']"
)


def test_get_parent_project() -> None:
    assert parentbuild.get_parent_project(PARENT + ":SLES") == PARENT
    assert parentbuild.get_parent_project(PARENT) is None


def test_get_parent_statuses_from_fake_data() -> None:
    statuses = parentbuild.get_parent_statuses(PARENT, fake_data=True)
    assert statuses is not None
    assert ("aarch64", "tree", "succeeded") in statuses
    assert ("ppc64le", "tree", "succeeded") in statuses


def test_get_parent_statuses_from_obs(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.parentbuild.http_GET", side_effect=lambda _url: "xml")
    mocker.patch(
        "osc.util.xml.xml_parse",
        return_value=etree.ElementTree(
            etree.fromstring(
                b'<resultlist><result arch="aarch64"><status package="tree" code="excluded"/></result></resultlist>'
            )
        ),
    )
    assert parentbuild.get_parent_statuses(PARENT, fake_data=False) == frozenset({("aarch64", "tree", "excluded")})


@pytest.mark.parametrize(
    "error",
    [
        HTTPError(f"{settings.obs_url}/build/{PARENT}/_result", 404, "Not found", cast("Any", {}), None),
        URLError("connection refused"),
        SyntaxError("not XML"),
    ],
    ids=["http_error", "connection_error", "unparseable"],
)
def test_get_parent_statuses_unreadable(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    caplog.set_level(logging.WARNING, logger="bot.loader.parentbuild")
    mocker.patch("openqabot.loader.parentbuild.http_GET", side_effect=error)
    assert parentbuild.get_parent_statuses(PARENT, fake_data=False) is None
    assert f"Parent build results of {PARENT} unreadable" in caplog.text


def test_get_parent_statuses_invalid_project(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    statuses = mocker.patch("openqabot.loader.parentbuild.http_GET")
    assert parentbuild.get_parent_statuses("../bad", fake_data=True) is None
    statuses.assert_not_called()
    assert "Invalid project name ../bad" in caplog.text


@pytest.mark.parametrize(
    ("statuses", "packages", "dropped", "warning"),
    [
        (
            frozenset({
                ("aarch64", UNKNOWN_PACKAGE, "excluded"),
                ("x86_64", UNKNOWN_PACKAGE, "succeeded"),
                ("x86_64", "unrelated", "excluded"),
            }),
            [UNKNOWN_PACKAGE],
            ["aarch64"],
            SKIPPING_WARNING,
        ),
        (
            frozenset({("aarch64", UNKNOWN_PACKAGE, "disabled")}),
            [UNKNOWN_PACKAGE],
            ["aarch64"],
            SKIPPING_WARNING,
        ),
        (
            frozenset({("aarch64", UNKNOWN_PACKAGE, "succeeded"), ("x86_64", UNKNOWN_PACKAGE, "succeeded")}),
            [UNKNOWN_PACKAGE],
            [],
            "",
        ),
        (
            frozenset({("aarch64", UNKNOWN_PACKAGE, "succeeded"), ("aarch64", UNKNOWN_PACKAGE, "excluded")}),
            [UNKNOWN_PACKAGE],
            [],
            UNDECIDED_WARNING,
        ),
        (
            frozenset({("aarch64", UNKNOWN_PACKAGE, "excluded"), ("x86_64", UNKNOWN_PACKAGE, "excluded")}),
            [UNKNOWN_PACKAGE],
            [],
            UNSUPPORTED_WARNING,
        ),
    ],
    ids=["arch_dropped", "disabled_arch_dropped", "all_archs_built", "conflicting_codes_kept", "all_archs_excluded"],
)
def test_filter_archs_by_parent_results(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    statuses: frozenset[tuple[str, str, str]],
    packages: list[str],
    dropped: list[str],
    warning: str,
) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.parentbuild")
    mocker.patch("openqabot.loader.parentbuild.get_parent_statuses", return_value=statuses)
    relevant_archs = {"aarch64", "x86_64"}
    res = parentbuild.filter_archs_by_parent_results(relevant_archs, packages, PARENT + ":SLES", fake_data=True)
    assert res == relevant_archs - set(dropped)
    if warning:
        assert warning in caplog.text
    else:
        assert not caplog.records


def test_filter_archs_by_parent_results_warns_on_incomplete_statuses(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="bot.loader.parentbuild")
    statuses = frozenset({("x86_64", UNKNOWN_PACKAGE, "excluded")})
    mocker.patch("openqabot.loader.parentbuild.get_parent_statuses", return_value=statuses)
    res = parentbuild.filter_archs_by_parent_results(
        {"aarch64", "x86_64"}, [UNKNOWN_PACKAGE], PARENT + ":SLES", fake_data=True
    )
    assert res == {"aarch64"}
    assert f"Parent build results of {PARENT} do not report every package ['{UNKNOWN_PACKAGE}']" in caplog.text
    assert "on archs ['aarch64'], keeping them" in caplog.text


def test_filter_archs_by_parent_results_untouched(mocker: MockerFixture) -> None:
    statuses = mocker.patch("openqabot.loader.parentbuild.get_parent_statuses")
    assert parentbuild.filter_archs_by_parent_results({"aarch64"}, [], PARENT + ":SLES", fake_data=True) == {"aarch64"}
    assert parentbuild.filter_archs_by_parent_results({"aarch64"}, ["pkg"], "project", fake_data=True) == {"aarch64"}
    statuses.assert_not_called()


def test_filter_archs_by_parent_results_unreadable(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.parentbuild.get_parent_statuses", return_value=None)
    res = parentbuild.filter_archs_by_parent_results({"aarch64"}, ["pkg"], PARENT + ":SLES", fake_data=True)
    assert res == {"aarch64"}
