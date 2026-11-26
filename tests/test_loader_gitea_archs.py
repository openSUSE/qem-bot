# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader Gitea archs."""

from urllib.error import URLError

import pytest
from pytest_mock import MockerFixture

from openqabot.config import settings
from openqabot.loader import gitea


def test_determine_relevant_archs_from_multibuild_info_success(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.read_utf8", return_value="xml")
    mocker.patch(
        "openqabot.loader.gitea.MultibuildFlavorResolver.parse_multibuild_data",
        return_value=["prod_x86_64", "prod_offline_aarch64", "other_flavor"],
    )
    mocker.patch("openqabot.loader.gitea.ARCHS", ["x86_64", "aarch64"])
    res = gitea.determine_relevant_archs_from_multibuild_info("project", fake_data=True)
    assert res == {"x86_64", "aarch64"}


def test_determine_relevant_archs_from_multibuild_info_not_fake(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_multibuild_data", return_value="xml")
    mocker.patch(
        "openqabot.loader.gitea.MultibuildFlavorResolver.parse_multibuild_data",
        return_value=["sles_x86_64"],
    )
    mocker.patch("openqabot.loader.gitea.ARCHS", ["x86_64"])
    res = gitea.determine_relevant_archs_from_multibuild_info("project", fake_data=False)
    assert res == {"x86_64"}


def test_determine_relevant_archs_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_multibuild_data", side_effect=URLError("oops"))
    res = gitea.determine_relevant_archs_from_multibuild_info("project", fake_data=False)
    assert res is None
    assert "Could not determine relevant architectures for project: <urlopen error oops>" in caplog.text


@pytest.mark.parametrize(
    "flavors",
    [
        [],
        ["other_flavor"],
    ],
)
def test_determine_relevant_archs_no_arch_flavors(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture, flavors: list[str]
) -> None:
    mocker.patch("openqabot.loader.gitea.get_multibuild_data", return_value="xml")
    mocker.patch("openqabot.loader.gitea.MultibuildFlavorResolver.parse_multibuild_data", return_value=flavors)
    res = gitea.determine_relevant_archs_from_multibuild_info("project", fake_data=False)
    assert res is None
    assert "Could not determine relevant architectures for project: No arch-specific flavors found" in caplog.text


@pytest.mark.parametrize(
    ("packages", "expected"),
    [
        (["000productcompose", "000package-groups"], "000productcompose"),
        (["000package-groups", "000productcompose-nvidia"], "000productcompose-nvidia"),
        (["000productcompose-nvidia", "000productcompose"], "000productcompose"),
    ],
)
def test_get_multibuild_data(mocker: MockerFixture, packages: list[str], expected: str) -> None:
    mock_packagelist = mocker.patch("openqabot.loader.gitea.osc.core.meta_get_packagelist", return_value=packages)
    mock_resolver = mocker.patch("openqabot.loader.gitea.MultibuildFlavorResolver")
    mock_resolver.return_value.get_multibuild_data.return_value = "data"
    assert gitea.get_multibuild_data("proj") == "data"
    mock_packagelist.assert_called_once_with(settings.obs_url, "proj")
    mock_resolver.assert_called_with(settings.obs_url, "proj", expected)


def test_get_multibuild_data_no_productcompose(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.osc.core.meta_get_packagelist", return_value=["000package-groups"])
    mock_resolver = mocker.patch("openqabot.loader.gitea.MultibuildFlavorResolver")
    assert not gitea.get_multibuild_data("proj")
    mock_resolver.assert_not_called()
