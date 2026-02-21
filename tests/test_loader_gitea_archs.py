# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader Gitea archs."""

from urllib.error import URLError

import pytest
from pytest_mock import MockerFixture

from openqabot.config import settings
from openqabot.loader import gitea


def test_determine_relevant_archs_from_multibuild_info_success(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="prod")
    mocker.patch("openqabot.loader.gitea.read_utf8", return_value="xml")
    mocker.patch("openqabot.loader.gitea.MultibuildFlavorResolver.parse_multibuild_data", return_value=["prod_x86_64"])
    mocker.patch("openqabot.loader.gitea.ARCHS", ["x86_64"])
    res = gitea.determine_relevant_archs_from_multibuild_info("project", dry=True)
    assert res is not None
    assert "x86_64" in res


def test_determine_relevant_archs_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="prod")
    mocker.patch("openqabot.loader.gitea.get_multibuild_data", side_effect=URLError("oops"))
    res = gitea.determine_relevant_archs_from_multibuild_info("project", dry=False)
    assert res is None
    assert "Could not determine relevant architectures for project: <urlopen error oops>" in caplog.text


def test_determine_relevant_archs_empty_product(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="")
    assert gitea.determine_relevant_archs_from_multibuild_info("project", dry=False) is None


def test_get_multibuild_data(mocker: MockerFixture) -> None:
    mock_resolver = mocker.patch("openqabot.loader.gitea.MultibuildFlavorResolver")
    mock_resolver.return_value.get_multibuild_data.return_value = "data"
    assert gitea.get_multibuild_data("proj") == "data"
    mock_resolver.assert_called_with(settings.obs_url, "proj", "000productcompose")
