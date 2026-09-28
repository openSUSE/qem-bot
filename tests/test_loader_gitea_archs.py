# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader Gitea archs."""

import logging
from urllib.error import URLError

import pytest
from pytest_mock import MockerFixture

from openqabot.config import settings
from openqabot.loader import gitea


def test_determine_relevant_archs_success(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.read_utf8", return_value="xml")
    mocker.patch(
        "openqabot.loader.gitea.MultibuildFlavorResolver.parse_multibuild_data",
        return_value=["prod_x86_64", "prod_offline_aarch64", "other_flavor"],
    )
    mocker.patch("openqabot.loader.gitea.ARCHS", ["x86_64", "aarch64"])
    res = gitea.determine_relevant_archs("project", fake_data=True)
    assert res == {"x86_64", "aarch64"}


def test_determine_relevant_archs_not_fake(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_multibuild_data", return_value="xml")
    mocker.patch(
        "openqabot.loader.gitea.MultibuildFlavorResolver.parse_multibuild_data",
        return_value=["sles_x86_64"],
    )
    mocker.patch("openqabot.loader.gitea.ARCHS", ["x86_64"])
    res = gitea.determine_relevant_archs("project", fake_data=False)
    assert res == {"x86_64"}


def test_determine_relevant_archs_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_multibuild_data", side_effect=URLError("oops"))
    res = gitea.determine_relevant_archs("project", fake_data=False)
    assert res is None
    assert "Could not determine relevant architectures for project: <urlopen error oops>" in caplog.text


def test_get_multibuild_data(mocker: MockerFixture) -> None:
    mock_resolver = mocker.patch("openqabot.loader.gitea.MultibuildFlavorResolver")
    mock_resolver.return_value.get_multibuild_data.return_value = "data"
    assert gitea.get_multibuild_data("proj") == "data"
    mock_resolver.assert_called_with(settings.obs_url, "proj", "000productcompose")


def test_determine_relevant_archs_drops_unsupported_arch(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    proj = "SUSE:SLFO:1.1.99:PullRequest:124:SLES"
    assert gitea.determine_relevant_archs(proj, packages=["kernel-64kb"], fake_data=True) == {"aarch64"}
    assert (
        "Skipping archs ['x86_64'] for " + proj + ": packages ['kernel-64kb'] are listed for other architectures"
    ) in caplog.text


@pytest.mark.parametrize(
    ("packages", "expected"),
    [
        (["systemd"], {"x86_64"}),
        (["kernel-default"], {"x86_64", "aarch64"}),
        (["nonexistent"], {"x86_64", "aarch64"}),
        (["systemd", "kernel-default"], {"x86_64"}),
        (["systemd", "nonexistent"], {"x86_64"}),
    ],
    ids=["single_arch", "all_archs", "unknown_package_kept", "partial_support_dropped", "known_plus_unknown"],
)
def test_determine_relevant_archs_filtering(mocker: MockerFixture, packages: list[str], expected: set[str]) -> None:
    mocker.patch("openqabot.loader.gitea.read_utf8", return_value="xml")
    mocker.patch(
        "openqabot.loader.gitea.MultibuildFlavorResolver.parse_multibuild_data",
        return_value=["sles_x86_64", "sles_aarch64"],
    )
    mocker.patch("openqabot.loader.gitea.ARCHS", {"x86_64", "aarch64"})
    pc_map = {
        "x86_64": frozenset({"systemd", "kernel-default"}),
        "aarch64": frozenset({"kernel-default"}),
    }
    mocker.patch("openqabot.loader.gitea.get_productcompose_packages_per_arch", return_value=pc_map)
    res = gitea.determine_relevant_archs("proj", packages=packages, fake_data=True)
    assert res == expected


def test_determine_relevant_archs_keeps_all_when_no_arch_supports_every_package(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="bot.loader.gitea")
    proj = "SUSE:SLFO:1.1.99:PullRequest:124:SLES"
    res = gitea.determine_relevant_archs(proj, packages=["kernel-default", "kernel-64kb"], fake_data=True)
    assert res == {"x86_64", "aarch64"}
    assert f"No arch for {proj} supports all PR packages" in caplog.text


def test_determine_relevant_archs_productcompose_unavailable(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.read_utf8", return_value="xml")
    mocker.patch(
        "openqabot.loader.gitea.MultibuildFlavorResolver.parse_multibuild_data",
        return_value=["sles_x86_64"],
    )
    mocker.patch("openqabot.loader.gitea.ARCHS", {"x86_64"})
    mocker.patch("openqabot.loader.gitea.get_productcompose_packages_per_arch", return_value=None)
    res = gitea.determine_relevant_archs("proj", packages=["systemd"], fake_data=True)
    assert res == {"x86_64"}


def test_determine_relevant_archs_invalid_project(caplog: pytest.LogCaptureFixture) -> None:
    bad_proj = "SUSE:PullRequest:1:proj/../bad"
    assert gitea.determine_relevant_archs(bad_proj, fake_data=True) is None
    assert f"Invalid project name {bad_proj}" in caplog.text
