# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test loader productcompose."""

import logging
from concurrent import futures
from functools import partial

import pytest
from pytest_mock import MockerFixture

from openqabot.config import settings
from openqabot.loader import productcompose

FIXTURE_PROJECT = "SUSE:SLFO:1.1.99:PullRequest:124:SLES"


def test_productcompose_package_of_a_flavored_project(mocker: MockerFixture) -> None:
    mocker.patch("osc.core.meta_get_packagelist", return_value=["000productcompose-nvidia", "kernel-default"])

    assert (
        productcompose.productcompose_package("SUSE:SLFO:1.3:PullRequest:10936:SLES-NVIDIA")
        == "000productcompose-nvidia"
    )


def test_productcompose_package_defaults_without_a_discovered_package(mocker: MockerFixture) -> None:
    mocker.patch("osc.core.meta_get_packagelist", return_value=["kernel-default"])

    assert productcompose.productcompose_package("proj") == "000productcompose"


def test_productcompose_package_of_a_project_with_several_packages(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING, logger="bot.loader.productcompose")
    mocker.patch("osc.core.meta_get_packagelist", return_value=["000productcompose", "000productcompose-nvidia"])

    assert productcompose.productcompose_package("proj") == "000productcompose"
    assert "has several productcompose packages ['000productcompose', '000productcompose-nvidia']" in caplog.text


def test_get_productcompose_contents_of_a_flavored_package(mocker: MockerFixture) -> None:
    mocker.patch("osc.core.meta_get_packagelist", return_value=["000productcompose-nvidia"])
    mock_filelist = mocker.patch("osc.core.meta_get_filelist", return_value=["nvidia.productcompose"])
    mock_makeurl = mocker.patch("osc.core.makeurl", return_value="https://some-obs-url/nvidia.productcompose")
    mocker.patch(
        "openqabot.loader.productcompose.http_GET",
        return_value=mocker.Mock(read=mocker.Mock(return_value=b"yaml-content")),
    )

    assert productcompose.get_productcompose_contents("proj") == ["yaml-content"]

    mock_filelist.assert_called_with(settings.obs_url, "proj", "000productcompose-nvidia", expand=True)
    assert mock_makeurl.call_args.args[1][:3] == ["source", "proj", "000productcompose-nvidia"]


def test_get_productcompose_contents(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.productcompose.productcompose_package", return_value="000productcompose")
    mock_filelist = mocker.patch("osc.core.meta_get_filelist", return_value=["default.productcompose"])
    mocker.patch("osc.core.makeurl", return_value="https://some-obs-url/default.productcompose")
    mocker.patch(
        "openqabot.loader.productcompose.http_GET",
        return_value=mocker.Mock(read=mocker.Mock(return_value=b"yaml-content")),
    )
    assert productcompose.get_productcompose_contents("proj") == ["yaml-content"]
    mock_filelist.assert_called_with(settings.obs_url, "proj", "000productcompose", expand=True)


def test_get_productcompose_contents_merges_all_files(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.productcompose")
    mocker.patch("openqabot.loader.productcompose.productcompose_package", return_value="000productcompose")
    mocker.patch("osc.core.meta_get_filelist", return_value=["z.productcompose", "skip.txt", "a.productcompose"])
    mocker.patch("osc.core.makeurl", side_effect=lambda _url, parts: parts[-1])
    mocker.patch(
        "openqabot.loader.productcompose.http_GET",
        side_effect=lambda url: mocker.Mock(read=mocker.Mock(return_value=url.encode())),
    )
    assert productcompose.get_productcompose_contents("proj") == ["a.productcompose", "z.productcompose"]
    assert "Merging productcompose files of proj: ['a.productcompose', 'z.productcompose']" in caplog.text


def test_get_productcompose_contents_without_productcompose(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.loader.productcompose.productcompose_package", return_value="000productcompose")
    mocker.patch("osc.core.meta_get_filelist", return_value=["other.file"])
    assert productcompose.get_productcompose_contents("proj") == []


def test_get_productcompose_packages_per_arch_without_productcompose(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.productcompose")
    mocker.patch("openqabot.loader.productcompose.get_productcompose_contents", return_value=[])
    assert productcompose.get_productcompose_packages_per_arch("proj", fake_data=False) is None
    assert "No productcompose file for proj, not filtering architectures" in caplog.text


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
    mocker.patch("openqabot.loader.productcompose.read_utf8", return_value=yaml_content)
    res = productcompose.get_productcompose_packages_per_arch("proj", fake_data=True)
    assert res == {
        "x86_64": frozenset({"kernel-default", "systemd"}),
        "aarch64": frozenset({"kernel-default"}),
        "s390x": frozenset({"s390-tools"}),
    }


def test_get_productcompose_packages_per_arch_explicit_architectures(mocker: MockerFixture) -> None:
    yaml_content = """
packagesets:
  - name: sles
    architectures: [x86_64, aarch64]
    packages: [kernel-default]
  - name: sles_noarch
    architectures: [noarch]
    packages: [ignored]
  - name: sles_s390x
    architectures: x86_64
    packages: [s390-tools]
"""
    mocker.patch("openqabot.loader.productcompose.read_utf8", return_value=yaml_content)
    res = productcompose.get_productcompose_packages_per_arch("proj", fake_data=True)
    assert res == {
        "x86_64": frozenset({"kernel-default"}),
        "aarch64": frozenset({"kernel-default"}),
        "s390x": frozenset({"s390-tools"}),
    }


def test_get_productcompose_packages_per_arch_merges_files(mocker: MockerFixture) -> None:
    contents = [
        "packagesets:\n  - name: sles_x86_64\n    packages: [kernel-default]\n",
        "packagesets:\n  - name: sled_x86_64\n    packages: [biosdevname]\n",
    ]
    mocker.patch("openqabot.loader.productcompose.get_productcompose_contents", return_value=contents)
    res = productcompose.get_productcompose_packages_per_arch("proj", fake_data=False)
    assert res == {"x86_64": frozenset({"kernel-default", "biosdevname"})}


def test_get_productcompose_packages_per_arch_fails_open_on_broken_file(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    contents = ["packagesets:\n  - name: sles_x86_64\n    packages: [kernel-default]\n", "invalid: yaml: :"]
    mocker.patch("openqabot.loader.productcompose.get_productcompose_contents", return_value=contents)
    assert productcompose.get_productcompose_packages_per_arch("proj", fake_data=False) is None
    assert "Could not parse productcompose YAML for proj" in caplog.text


def test_get_productcompose_packages_per_arch_fixture(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="bot.loader.productcompose")
    res = productcompose.get_productcompose_packages_per_arch(FIXTURE_PROJECT, fake_data=True)
    assert res == {
        "x86_64": frozenset({"biosdevname", "crash-gcore", "kernel-default"}),
        "aarch64": frozenset({"arm-trusted-firmware", "kernel-64kb"}),
    }
    assert "Malformed group" not in caplog.text
    assert "Group sles_x86_64_installer in productcompose lists no packages" in caplog.text


def test_get_productcompose_packages_per_arch_fetch_error(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    mocker.patch("openqabot.loader.productcompose.productcompose_package", return_value="000productcompose")
    mocker.patch("osc.core.meta_get_filelist", return_value=["default.productcompose"])
    mocker.patch("osc.core.makeurl", return_value="https://some-obs-url/default.productcompose")
    mocker.patch("openqabot.loader.productcompose.http_GET", side_effect=OSError("boom"))
    assert productcompose.get_productcompose_packages_per_arch("proj", fake_data=False) is None
    assert "Could not fetch productcompose for proj: boom" in caplog.text


def test_get_productcompose_packages_per_arch_invalid_yaml(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    mocker.patch("openqabot.loader.productcompose.read_utf8", return_value="invalid: yaml: :")
    res = productcompose.get_productcompose_packages_per_arch("proj", fake_data=True)
    assert res is None
    assert "Could not parse productcompose YAML for proj" in caplog.text


def test_get_productcompose_packages_per_arch_invalid_structure(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    mocker.patch("openqabot.loader.productcompose.read_utf8", return_value="just a string")
    res = productcompose.get_productcompose_packages_per_arch("proj", fake_data=True)
    assert res is None
    assert "Malformed productcompose document for proj: <class 'str'>" in caplog.text


def test_get_productcompose_packages_per_arch_invalid_elements(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.productcompose")
    yaml_content = """
packagesets:
  - 123
  - name: 456
    packages: [kernel-default]
  - name: sles_x86_64
    packages: not-a-list
"""
    mocker.patch("openqabot.loader.productcompose.read_utf8", return_value=yaml_content)
    res = productcompose.get_productcompose_packages_per_arch("proj", fake_data=True)
    assert res is None
    assert "Malformed group in productcompose: <class 'int'>" in caplog.text
    assert "Malformed group in productcompose without a name: ['name', 'packages']" in caplog.text
    assert "Malformed packages in group sles_x86_64 of productcompose: <class 'str'>" in caplog.text
    assert "No arch-specific packagesets in productcompose of proj" in caplog.text


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("packagesets:\n", "No arch-specific packagesets in productcompose of proj"),
        ("packagesets: {a: b}\n", "Malformed packagesets in productcompose of proj: <class 'dict'>"),
    ],
    ids=["empty", "not_a_list"],
)
def test_get_productcompose_packages_per_arch_without_packagesets(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture, content: str, expected: str
) -> None:
    caplog.set_level(logging.INFO, logger="bot.loader.productcompose")
    mocker.patch("openqabot.loader.productcompose.read_utf8", return_value=content)
    assert productcompose.get_productcompose_packages_per_arch("proj", fake_data=True) is None
    assert expected in caplog.text


def test_get_productcompose_packages_per_arch_invalid_project(caplog: pytest.LogCaptureFixture) -> None:
    assert productcompose.get_productcompose_packages_per_arch("proj/../bad", fake_data=True) is None
    assert "Invalid project name proj/../bad" in caplog.text


def test_get_productcompose_packages_per_arch_concurrent(mocker: MockerFixture) -> None:
    def fake_productcompose(project: str) -> list[str]:
        return [f"packagesets:\n  - name: sles_{project}_x86_64\n    packages: [pkg-{project}]\n"]

    mocker.patch("openqabot.loader.productcompose.get_productcompose_contents", side_effect=fake_productcompose)
    projects = [f"pr{i}" for i in range(32)]
    with futures.ThreadPoolExecutor(max_workers=16) as executor:
        results = list(
            executor.map(partial(productcompose.get_productcompose_packages_per_arch, fake_data=False), projects)
        )
    assert results == [{"x86_64": frozenset({f"pkg-{project}"})} for project in projects]
