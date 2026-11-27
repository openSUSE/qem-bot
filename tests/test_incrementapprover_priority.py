# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test the product increment priority derivation."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

import pytest

from openqabot.errors import LoaderQemError
from openqabot.loader.incrementconfig import IncrementConfig
from openqabot.priority import dashboard_submissions
from openqabot.repodiff import Package
from openqabot.types.increment import BuildInfo
from openqabot.types.submission import Submission

from .helpers import prepare_approver

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

    from openqabot.incrementapprover import IncrementApprover

BUILD_INFO = BuildInfo("sle", "SLES", "16.0", "Online-Increments", "x86_64", "1.1")


def make_submission(
    priority: int | None,
    *packages: str,
    channel_version: str = "16.0",
    channel: str | None = None,
    approved: bool = False,
    active: bool = True,
) -> Submission:
    number = (priority or 0) + len(packages)
    return Submission({
        "number": number,
        "rr_number": number * 100,
        "project": f"SUSE:Maintenance:{number}",
        "inReview": True,
        "isActive": active,
        "approved": approved,
        "inReviewQAM": True,
        "embargoed": False,
        "channels": [channel or f"SUSE:Updates:SLE-Server:{channel_version}:x86_64"],
        "packages": list(packages),
        "emu": False,
        "priority": priority,
    })


def make_config(**overrides: Any) -> IncrementConfig:
    defaults: dict[str, Any] = {
        "distri": "sle",
        "version": "16.0",
        "flavor": "Online-Increments",
        "project_base": "OBS:PROJECT",
        "build_project_suffix": "TEST",
        "build_listing_sub_path": "product",
        "build_regex": ".*",
        "product_regex": ".*",
        "reference_repos": {"SLES": "http://download.suse.de/ibs/Products/SLES/16.0"},
    }
    return IncrementConfig(**(defaults | overrides))


def prepare_priority_approver(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    *packages: str,
) -> IncrementApprover:
    approver = prepare_approver(caplog)
    package_diff = defaultdict(set, {"x86_64": {Package(name, "1", "2", "3", "x86_64") for name in packages}})
    mocker.patch.object(approver, "get_package_diff_from_repo", return_value=package_diff)
    return approver


def use_submissions(mocker: MockerFixture, submissions: list[Submission]) -> None:
    mocker.patch("openqabot.priority.get_submissions", return_value=submissions)
    dashboard_submissions.cache_clear()


@pytest.mark.parametrize(
    ("submissions", "build_version", "expected_priority"),
    [
        ([], "16.0", "420"),
        ([make_submission(0, "kernel-default")], "16.0", "420"),
        ([make_submission(None, "kernel-default")], "16.0", "420"),
        ([make_submission(200, "kernel-default")], "16.0", "380"),
        ([make_submission(650, "kernel-default")], "16.0", "290"),
        ([make_submission(780, "kernel-default")], "16.0", "264"),
        ([make_submission(780, "kernel-default", approved=True)], "16.0", "264"),
        ([make_submission(1500, "kernel-default", approved=True)], "16.0", "120"),
        ([make_submission(1500, "kernel-default", active=False)], "16.0", "420"),
        ([make_submission(1000, "kernel-default")], "16.0", "220"),
        ([make_submission(1500, "kernel-default")], "16.0", "120"),
        ([make_submission(780, "samba"), make_submission(1000, "kernel-default")], "16.0", "220"),
        ([make_submission(1500, "kernel-default", channel_version="15-SP4")], "16.0", "420"),
        ([make_submission(1500, "samba")], "16.0", "420"),
        ([make_submission(780, "kernel-default", channel_version="12")], "12-SP5", "264"),
        ([make_submission(780, "kernel-default", channel_version="16")], "16.0", "264"),
        (
            [make_submission(1500, "kernel-default", channel="SUSE:SLFO:1.2:PullRequest:1696:SLES:x86_64#16.0")],
            "16.0",
            "120",
        ),
    ],
)
def test_scheduling_parameters_derive_priority(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    submissions: list[Submission],
    build_version: str,
    expected_priority: str,
) -> None:
    approver = prepare_priority_approver(mocker, caplog, "kernel-default")
    use_submissions(mocker, submissions)

    res = approver.make_scheduling_parameters(make_config(), BUILD_INFO._replace(version=build_version), 42)

    assert res[0]["_PRIORITY"] == expected_priority


def test_scheduling_parameters_log_included_update_priority(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    approver = prepare_priority_approver(mocker, caplog, "kernel-default")
    use_submissions(mocker, [make_submission(780, "kernel-default")])
    caplog.set_level(logging.INFO, logger="bot.priority")

    approver.make_scheduling_parameters(make_config(), BUILD_INFO, 42)

    assert "openQA priority 264 from maximum included update priority 780" in caplog.text


def test_scheduling_parameters_without_reference_repos(caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_approver(caplog)

    res = approver.make_scheduling_parameters(make_config(reference_repos={}), BUILD_INFO, 42)

    assert "_PRIORITY" not in res[0]


def test_scheduling_parameters_with_only_null_reference_repos(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    approver = prepare_approver(caplog)
    get_package_diff = mocker.patch.object(approver, "get_package_diff_from_repo")

    res = approver.make_scheduling_parameters(make_config(reference_repos={"SLES": None}), BUILD_INFO, 42)

    assert "_PRIORITY" not in res[0]
    get_package_diff.assert_not_called()


def test_scheduling_parameters_without_dashboard(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_priority_approver(mocker, caplog, "kernel-default")
    get_submissions = mocker.patch("openqabot.priority.get_submissions", side_effect=LoaderQemError("dashboard down"))
    dashboard_submissions.cache_clear()

    res = approver.make_scheduling_parameters(make_config(), BUILD_INFO, 42)
    approver.make_scheduling_parameters(make_config(), BUILD_INFO, 42)

    assert res[0]["_PRIORITY"] == "420"
    assert "Could not load submissions for priority derivation: dashboard down" in caplog.text
    assert get_submissions.call_count == 1


def test_scheduling_parameters_reuse_loaded_submissions(
    mocker: MockerFixture, caplog: pytest.LogCaptureFixture
) -> None:
    approver = prepare_priority_approver(mocker, caplog, "kernel-default")
    get_submissions = mocker.patch(
        "openqabot.priority.get_submissions", return_value=[make_submission(780, "kernel-default")]
    )
    dashboard_submissions.cache_clear()

    first = approver.make_scheduling_parameters(make_config(), BUILD_INFO, 42)
    second = approver.make_scheduling_parameters(make_config(), BUILD_INFO, 42)

    assert first[0]["_PRIORITY"] == second[0]["_PRIORITY"] == "264"
    assert get_submissions.call_count == 1


def test_settings_override_derived_priority(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_priority_approver(mocker, caplog, "kernel-default")
    use_submissions(mocker, [make_submission(780, "kernel-default")])

    res = approver.make_scheduling_parameters(make_config(settings={"_PRIORITY": "300"}), BUILD_INFO, 42)

    assert res[0]["_PRIORITY"] == "300"


def test_additional_builds_inherit_derived_priority(mocker: MockerFixture, caplog: pytest.LogCaptureFixture) -> None:
    approver = prepare_priority_approver(mocker, caplog, "kernel-default")
    use_submissions(mocker, [make_submission(780, "kernel-default")])
    config = make_config(
        additional_builds=[
            {
                "archs": ["x86_64"],
                "build_suffix": "additional-build",
                "package_name_regex": ".*",
                "settings": {"FLAVOR": "Additional-Increments"},
            }
        ]
    )

    res = approver.make_scheduling_parameters(config, BUILD_INFO, 42)

    assert len(res) == 2
    assert {params["_PRIORITY"] for params in res} == {"264"}
