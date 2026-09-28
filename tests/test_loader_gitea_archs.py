# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader Gitea archs."""

import logging
from concurrent import futures
from functools import partial
from urllib.error import URLError

import pytest
from pytest_mock import MockerFixture

from openqabot.config import settings
from openqabot.loader import gitea


def test_determine_relevant_archs_success(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="prod")
    mocker.patch("openqabot.loader.gitea.read_utf8", return_value="xml")
    mocker.patch("openqabot.loader.gitea.MultibuildFlavorResolver.parse_multibuild_data", return_value=["prod_x86_64"])
    mocker.patch("openqabot.loader.gitea.ARCHS", {"x86_64"})
    res = gitea.determine_relevant_archs("project", fake_data=True)
    assert res is not None
    assert "x86_64" in res


def test_determine_relevant_archs_exception(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="prod")
    mocker.patch("openqabot.loader.gitea.get_multibuild_data", side_effect=URLError("oops"))
    res = gitea.determine_relevant_archs("project", fake_data=False)
    assert res is None
    assert "Could not determine relevant architectures for project: <urlopen error oops>" in caplog.text


def test_determine_relevant_archs_empty_product(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="")
    assert gitea.determine_relevant_archs("project", fake_data=False) is None


def test_get_multibuild_data(mocker: MockerFixture) -> None:
    mock_resolver = mocker.patch("openqabot.loader.gitea.MultibuildFlavorResolver")
    mock_resolver.return_value.get_multibuild_data.return_value = "data"
    assert gitea.get_multibuild_data("proj") == "data"
    mock_resolver.assert_called_with(settings.obs_url, "proj", "000productcompose")


def test_get_productcompose_data(mocker: MockerFixture) -> None:
    mock_filelist = mocker.patch("osc.core.meta_get_filelist", return_value=["default.productcompose"])
    mocker.patch("osc.core.makeurl", return_value="https://some-obs-url/default.productcompose")
    mocker.patch(
        "openqabot.loader.gitea.http_GET",
        return_value=mocker.Mock(read=mocker.Mock(return_value=b"yaml-content")),
    )
    assert gitea.get_productcompose_data("proj") == "yaml-content"
    mock_filelist.assert_called_with(settings.obs_url, "proj", "000productcompose", expand=True)


def test_get_productcompose_data_not_found(mocker: MockerFixture) -> None:
    mocker.patch("osc.core.meta_get_filelist", return_value=["other.file"])
    with pytest.raises(FileNotFoundError, match=r"No \.productcompose file found in 000productcompose for proj"):
        gitea.get_productcompose_data("proj")


def test_get_productcompose_packages_per_arch_groups(mocker: MockerFixture) -> None:
    yaml_content = """
     packagesets:
       - name: sles_x86_64
         packages:
           - kernel-default
           - systemd
           - 123
       - name: sle_aarch64_module
         packages:
           - kernel-default
       - name: s390x
         packages:
           - s390-tools
     """
    mocker.patch("openqabot.loader.gitea.read_utf8", return_value=yaml_content)
    res = gitea.get_productcompose_packages_per_arch("proj", fake_data=True)
    assert res == {
        "x86_64": frozenset({"kernel-default", "systemd"}),
        "aarch64": frozenset({"kernel-default"}),
        "s390x": frozenset({"s390-tools"}),
    }


def test_get_productcompose_packages_per_arch_live(mocker: MockerFixture) -> None:
    live_response = mocker.Mock(
        read=mocker.Mock(return_value=b"packagesets:\n  - name: sles_x86_64\n    packages:\n      - kernel-default\n")
    )
    mocker.patch("osc.core.meta_get_filelist", return_value=["default.productcompose"])
    mocker.patch("osc.core.makeurl", return_value="https://some-obs-url/default.productcompose")
    mocker.patch("openqabot.loader.gitea.http_GET", return_value=live_response)
    res = gitea.get_productcompose_packages_per_arch("proj", fake_data=False)
    assert res == {"x86_64": frozenset({"kernel-default"})}


def test_get_productcompose_packages_per_arch_fetch_error(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    mocker.patch("osc.core.meta_get_filelist", return_value=["other.xml"])
    res = gitea.get_productcompose_packages_per_arch("proj", fake_data=False)
    assert res is None
    assert "Could not fetch productcompose for proj" in caplog.text


def test_get_productcompose_packages_per_arch_invalid_yaml(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    mocker.patch("openqabot.loader.gitea.read_utf8", return_value="invalid: yaml: :")
    res = gitea.get_productcompose_packages_per_arch("proj", fake_data=True)
    assert res is None
    assert "Could not parse productcompose YAML for proj" in caplog.text


def test_get_productcompose_packages_per_arch_invalid_structure(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    mocker.patch("openqabot.loader.gitea.read_utf8", return_value="just a string")
    res = gitea.get_productcompose_packages_per_arch("proj", fake_data=True)
    assert res is None
    assert "No valid architectures found in productcompose for proj, top-level keys <class 'str'>" in caplog.text


def test_get_productcompose_packages_per_arch_invalid_elements(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    yaml_content = """
packagesets:
  - 123
  - name: 456
    packages: [kernel-default]
  - name: sles_x86_64
    packages: not-a-list
"""
    mocker.patch("openqabot.loader.gitea.read_utf8", return_value=yaml_content)
    res = gitea.get_productcompose_packages_per_arch("proj", fake_data=True)
    assert res is None
    assert "Malformed group in productcompose: <class 'int'>" in caplog.text
    assert "Malformed group in productcompose: dict_keys(['name', 'packages'])" in caplog.text
    assert "No valid architectures found in productcompose for proj, top-level keys ['packagesets']" in caplog.text


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
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="prod")
    mocker.patch("openqabot.loader.gitea.read_utf8", return_value="xml")
    mocker.patch(
        "openqabot.loader.gitea.MultibuildFlavorResolver.parse_multibuild_data",
        return_value=["prod_x86_64", "prod_aarch64"],
    )
    mocker.patch("openqabot.loader.gitea.ARCHS", {"x86_64", "aarch64"})
    pc_map = {
        "x86_64": frozenset({"systemd", "kernel-default"}),
        "aarch64": frozenset({"kernel-default"}),
    }
    mocker.patch("openqabot.loader.gitea.get_productcompose_packages_per_arch", return_value=pc_map)
    res = gitea.determine_relevant_archs("proj", packages=packages, fake_data=True)
    assert res == expected


def test_determine_relevant_archs_productcompose_unavailable(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="prod")
    mocker.patch("openqabot.loader.gitea.read_utf8", return_value="xml")
    mocker.patch(
        "openqabot.loader.gitea.MultibuildFlavorResolver.parse_multibuild_data",
        return_value=["prod_x86_64"],
    )
    mocker.patch("openqabot.loader.gitea.ARCHS", {"x86_64"})
    mocker.patch("openqabot.loader.gitea.get_productcompose_packages_per_arch", return_value=None)
    res = gitea.determine_relevant_archs("proj", packages=["systemd"], fake_data=True)
    assert res == {"x86_64"}


def test_determine_relevant_archs_logs_skipped_arch(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.gitea")
    mocker.patch("openqabot.loader.gitea.get_product_name", return_value="prod")
    mocker.patch("openqabot.loader.gitea.read_utf8", return_value="xml")
    mocker.patch(
        "openqabot.loader.gitea.MultibuildFlavorResolver.parse_multibuild_data",
        return_value=["prod_x86_64", "prod_aarch64"],
    )
    mocker.patch("openqabot.loader.gitea.ARCHS", {"x86_64", "aarch64"})
    pc_map = {
        "x86_64": frozenset({"systemd"}),
        "aarch64": frozenset({"other"}),
    }
    mocker.patch("openqabot.loader.gitea.get_productcompose_packages_per_arch", return_value=pc_map)
    res = gitea.determine_relevant_archs("proj", packages=["systemd"], fake_data=True)
    assert res == {"x86_64"}
    assert "Skipping archs ['aarch64'] for proj: not all PR packages found in productcompose" in caplog.text


def test_determine_relevant_archs_invalid_project(caplog: pytest.LogCaptureFixture) -> None:
    bad_proj = "SUSE:PullRequest:1:proj/../bad"
    assert gitea.determine_relevant_archs(bad_proj, fake_data=True) is None
    assert f"Invalid project name {bad_proj}" in caplog.text


def test_get_productcompose_packages_per_arch_invalid_project(caplog: pytest.LogCaptureFixture) -> None:
    assert gitea.get_productcompose_packages_per_arch("proj/../bad", fake_data=True) is None
    assert "Invalid project name proj/../bad" in caplog.text


def test_get_productcompose_packages_per_arch_concurrent(mocker: MockerFixture) -> None:
    def fake_productcompose(project: str) -> str:
        return f"packagesets:\n  - name: sles_{project}_x86_64\n    packages: [pkg-{project}]\n"

    mocker.patch("openqabot.loader.gitea.get_productcompose_data", side_effect=fake_productcompose)
    projects = [f"pr{i}" for i in range(32)]
    with futures.ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(partial(gitea.get_productcompose_packages_per_arch, fake_data=False), projects))
    assert results == [{"x86_64": frozenset({f"pkg-{project}"})} for project in projects]
