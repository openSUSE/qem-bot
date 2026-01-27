# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
from typing import Any

import pytest
from pytest_mock import MockerFixture

from openqabot.config import DEFAULT_SUBMISSION_TYPE
from openqabot.errors import NoRepoFoundError
from openqabot.types.baseconf import JobConfig
from openqabot.types.submission import Submission
from openqabot.types.submissions import SubConfig, SubContext, Submissions
from openqabot.types.types import ArchVer, Repos

from .fixtures.submissions import MockSubmission


def _get_submissions_obj(
    test_config: dict | None = None, settings: dict | None = None, extrasettings: set | None = None
) -> Submissions:
    if test_config is None:
        test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    if settings is None:
        settings = {"VERSION": "15-SP3", "DISTRI": "SLES"}
    if extrasettings is None:
        extrasettings = set()
    return Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings=settings,
            config=test_config,
        ),
        extrasettings=extrasettings,
    )


def test_get_submissions_obj_coverage() -> None:
    # Trigger all branches in _get_submissions_obj
    _get_submissions_obj(test_config={"FLAVOR": {}}, settings={"V": "1"}, extrasettings=set())


@pytest.mark.parametrize(("rev_val", "fallback_val"), [(False, True), (True, None)])
def test_handle_submission_rev_coverage(mocker: MockerFixture, *, rev_val: bool, fallback_val: int | None) -> None:
    submissions_obj = _get_submissions_obj()
    sub = MockSubmission()
    mocker.patch("openqabot.types.submissions.Submission.compute_revisions_for_product_repo", return_value=rev_val)
    mocker.patch("openqabot.types.submissions.Submission.revisions_with_fallback", return_value=fallback_val)
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data={})
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    assert submissions_obj.handle_submission(ctx, cfg) is None


def test_handle_submission_git_not_ongoing() -> None:
    sub_data = {
        "number": 123,
        "rr_number": 1,
        "project": "SUSE:Maintenance:123",
        "inReview": True,
        "isActive": False,
        "embargoed": False,
        "packages": ["foo"],
        "channels": ["SUSE:Updates:SLE-Product-SLES:15-SP3:x86_64"],
        "emu": False,
        "type": "git",
    }
    sub = Submission(sub_data)

    test_config = {"FLAVOR": {"AAA": {"archs": [""], "issues": {}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "", "DISTRI": None},
            config=test_config,
        ),
        extrasettings=set(),
    )

    ctx = SubContext(sub=sub, arch="", flavor="AAA", data={})
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)

    result = submissions_obj.handle_submission(ctx, cfg)
    assert result is None


def test_handle_submission_with_ci_url(mocker: MockerFixture) -> None:
    sub_data = {
        "number": 123,
        "rr_number": 1,
        "project": "SUSE:Maintenance:123",
        "inReview": True,
        "isActive": True,
        "inReviewQAM": True,
        "approved": False,
        "embargoed": False,
        "packages": ["foo"],
        "channels": ["SUSE:Updates:SLE-Product-SLES:15-SP3:x86_64"],
        "emu": False,
        "type": DEFAULT_SUBMISSION_TYPE,
    }
    sub = Submission(sub_data)

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLE-Product-SLES:15-SP3"}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo="SLE-Product-SLES",
            product_version="15-SP3",
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    submissions_obj.singlearch = set()

    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=submissions_obj.flavors["AAA"])
    cfg = SubConfig(token={}, ci_url="http://my-ci.com/123", ignore_onetime=True)

    mocker.patch("openqabot.types.submission.get_max_revision", return_value=123)
    result = submissions_obj.handle_submission(ctx, cfg)

    assert result is not None
    assert result["openqa"]["__CI_JOB_URL"] == "http://my-ci.com/123"


def test_is_scheduled_job_error(mocker: MockerFixture) -> None:
    sub = MockSubmission()
    sub.id = 1
    mocker.patch("openqabot.types.submissions.retried_requests.get").return_value.json.return_value = {"error": "foo"}
    ctx = SubContext(sub, "arch", "flavor", {})
    assert not Submissions.is_scheduled_job({}, ctx, "ver")


def test_is_scheduled_job_no_revs(mocker: MockerFixture) -> None:
    sub = MockSubmission()
    sub.id = 1
    mocker.patch("openqabot.types.submissions.retried_requests.get").return_value.json.return_value = [{"id": 1}]
    mocker.patch.object(sub, "revisions_with_fallback", return_value=None)
    ctx = SubContext(sub, "arch", "flavor", {})
    assert not Submissions.is_scheduled_job({}, ctx, "ver")


def test_handle_submission_embargoed_skip() -> None:
    sub = MockSubmission()
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    # Patch filter_embargoed to return True
    submissions_obj.filter_embargoed = lambda _: True  # type: ignore[invalid-assignment]
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data={})
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    assert submissions_obj.handle_submission(ctx, cfg) is None


def test_handle_submission_staging_skip() -> None:
    sub = MockSubmission()
    sub.staging = True
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data={})
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    assert submissions_obj.handle_submission(ctx, cfg) is None

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    data = {"packages": ["somepkg"]}
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=data)
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    assert submissions_obj.handle_submission(ctx, cfg) is None


def test_handle_submission_excluded_packages_skip() -> None:
    sub = MockSubmission(id=1, contains_package_value=True)
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    data = {"excluded_packages": ["badpkg"]}
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=data)
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    assert submissions_obj.handle_submission(ctx, cfg) is None


def test_handle_submission_livepatch_kgraft(mocker: MockerFixture) -> None:
    sub = MockSubmission(
        id=1,
        livepatch=True,
        packages=["kernel-livepatch-foo"],
        channels=[Repos("SLES", "15-SP3", "x86_64")],
        rev_fallback_value=123,
    )

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=submissions_obj.flavors["AAA"])
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    # Mock is_scheduled_job to return False
    mocker.patch.object(submissions_obj, "is_scheduled_job", return_value=False)

    result = submissions_obj.handle_submission(ctx, cfg)
    assert result is not None
    assert result["openqa"]["KGRAFT"] == "1"


def test_handle_submission_no_issue_skip() -> None:
    sub = MockSubmission(id=1, channels=[], rev_fallback_value=123)

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=submissions_obj.flavors["AAA"])
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    assert submissions_obj.handle_submission(ctx, cfg) is None


def test_handle_submission_required_issues_skip() -> None:
    sub = MockSubmission(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)

    test_config = {
        "FLAVOR": {
            "AAA": {
                "archs": ["x86_64"],
                "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"},
                "required_issues": ["LTSS_TEST_ISSUES"],
            }
        }
    }
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=submissions_obj.flavors["AAA"])
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    assert submissions_obj.handle_submission(ctx, cfg) is None


def test_handle_submission_already_scheduled(mocker: MockerFixture) -> None:
    sub = MockSubmission(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=submissions_obj.flavors["AAA"])
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(submissions_obj, "is_scheduled_job", return_value=True)
    assert submissions_obj.handle_submission(ctx, cfg) is None


def test_handle_submission_kernel_no_product_repo_skip(mocker: MockerFixture) -> None:
    sub = MockSubmission(id=1, livepatch=False, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)

    test_config = {
        "FLAVOR": {
            "SomeKernel-Flavor": {
                "archs": ["x86_64"],
                "issues": {"NOT_PRODUCT_REPO": "SLES:15-SP3"},
            }
        }
    }
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    ctx = SubContext(
        sub=sub,
        arch="x86_64",
        flavor="SomeKernel-Flavor",
        data=submissions_obj.flavors["SomeKernel-Flavor"],
    )
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(submissions_obj, "is_scheduled_job", return_value=False)

    assert submissions_obj.handle_submission(ctx, cfg) is None


def test_handle_submission_singlearch_no_aggregate(mocker: MockerFixture) -> None:
    sub = MockSubmission(
        id=1,
        packages=["singlepkg"],
        channels=[Repos("SLES", "15-SP3", "x86_64")],
        rev_fallback_value=123,
    )

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings={"singlepkg"},
    )
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=submissions_obj.flavors["AAA"])
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(submissions_obj, "is_scheduled_job", return_value=False)

    result = submissions_obj.handle_submission(ctx, cfg)
    assert result is not None
    assert result["qem"]["withAggregate"] is False


@pytest.mark.parametrize(
    "aggregate_check",
    [
        {"aggregate_check_true": ["OS_TEST_ISSUES"]},
        {"aggregate_check_false": ["OS_TEST_ISSUES"]},
        {"aggregate_check_false": ["SOMETHING_ELSE"]},
    ],
)
def test_handle_submission_should_aggregate_logic(mocker: MockerFixture, aggregate_check: dict) -> None:
    sub = MockSubmission(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)
    flavor_data: dict[str, Any] = {
        "archs": ["x86_64"],
        "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"},
        "aggregate_job": False,
    }
    flavor_data.update(aggregate_check)

    test_config = {"FLAVOR": {"AAA": flavor_data}}
    submissions_obj = _get_submissions_obj(test_config=test_config)
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=submissions_obj.flavors["AAA"])
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(submissions_obj, "is_scheduled_job", return_value=False)

    result = submissions_obj.handle_submission(ctx, cfg)
    assert result is not None
    assert result["qem"]["withAggregate"] is False


def test_handle_submission_params_expand_forbidden(mocker: MockerFixture) -> None:
    sub = MockSubmission(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)
    test_config = {
        "FLAVOR": {
            "AAA": {
                "archs": ["x86_64"],
                "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"},
                "params_expand": {"DISTRI": "forbidden"},
            }
        }
    }
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=submissions_obj.flavors["AAA"])
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(submissions_obj, "is_scheduled_job", return_value=False)

    assert submissions_obj.handle_submission(ctx, cfg) is None


def test_handle_submission_pc_tools_image_fail(mocker: MockerFixture) -> None:
    sub = MockSubmission(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES", "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY": "test"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=submissions_obj.flavors["AAA"])
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(submissions_obj, "is_scheduled_job", return_value=False)
    mocker.patch("openqabot.types.submissions.apply_pc_tools_image", return_value={})

    assert submissions_obj.handle_submission(ctx, cfg) is None


def test_handle_submission_pc_pint_image_fail(mocker: MockerFixture) -> None:
    sub = MockSubmission(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES", "PUBLIC_CLOUD_PINT_QUERY": "test"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=submissions_obj.flavors["AAA"])
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(submissions_obj, "is_scheduled_job", return_value=False)
    mocker.patch(
        "openqabot.types.submissions.apply_publiccloud_pint_image", return_value={"PUBLIC_CLOUD_IMAGE_ID": None}
    )

    assert submissions_obj.handle_submission(ctx, cfg) is None


def test_process_sub_context_norepfound(mocker: MockerFixture) -> None:
    sub = MockSubmission(id=1, project="project", packages=["pkg"])
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data={"archs": ["x86_64"]})
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(submissions_obj, "handle_submission", side_effect=NoRepoFoundError)
    with pytest.raises(NoRepoFoundError):
        submissions_obj.process_sub_context(ctx, cfg)


@pytest.mark.parametrize(
    ("inc_kwargs", "flavor_kwargs", "expected_prio"),
    [
        ({"emu": True, "staging": False}, {}, 30),
        ({"staging": False, "emu": False}, {}, 60),
        ({"staging": False, "emu": False}, {"override_priority": 50}, None),
        ({}, {"override_priority": 100}, 100),
        ({"staging": False}, {"flavor": "Minimal"}, 55),
        ({"staging": False, "priority": 100}, {}, 55),
        ({"staging": False, "emu": True, "priority": 100}, {}, 25),
    ],
)
def test_handle_submission_priority_logic(
    mocker: MockerFixture, inc_kwargs: dict, flavor_kwargs: dict, expected_prio: int | None
) -> None:
    flavor = flavor_kwargs.pop("flavor", "AAA")
    sub = MockSubmission(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123, **inc_kwargs)
    flavor_data = {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}
    flavor_data.update(flavor_kwargs)
    test_config = {"FLAVOR": {flavor: flavor_data}}
    submissions_obj = _get_submissions_obj(test_config=test_config)
    ctx = SubContext(sub=sub, arch="x86_64", flavor=flavor, data=submissions_obj.flavors[flavor])
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(submissions_obj, "is_scheduled_job", return_value=False)
    result = submissions_obj.handle_submission(ctx, cfg)
    assert result is not None
    if expected_prio is None:
        assert "_PRIORITY" not in result["openqa"]
    else:
        assert result["openqa"]["_PRIORITY"] == expected_prio


def test_handle_submission_pc_tools_image_success(mocker: MockerFixture) -> None:
    sub = MockSubmission(id=1, channels=[Repos("SLES", "15-SP3", "x86_64")], rev_fallback_value=123)
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLES:15-SP3"}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES", "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY": "test"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=submissions_obj.flavors["AAA"])
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    mocker.patch.object(submissions_obj, "is_scheduled_job", return_value=False)
    mocker.patch(
        "openqabot.types.submissions.apply_pc_tools_image",
        return_value={"PUBLIC_CLOUD_TOOLS_IMAGE_BASE": "some_image"},
    )
    result = submissions_obj.handle_submission(ctx, cfg)
    assert result is not None
    assert result["openqa"]["PUBLIC_CLOUD_TOOLS_IMAGE_BASE"] == "some_image"

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    mocker.patch(
        "openqabot.types.submissions.apply_publiccloud_pint_image",
        return_value={"PUBLIC_CLOUD_IMAGE_ID": "ami-12345"},
    )
    settings = {"PUBLIC_CLOUD_PINT_QUERY": "query"}
    result = submissions_obj.apply_pc_images(settings)
    assert result == {"PUBLIC_CLOUD_IMAGE_ID": "ami-12345"}


def test_handle_submission_no_revisions_return_none() -> None:
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    sub_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    sub = MockSubmission(id=1, rrid="RRID", revisions=None, channels=[])
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data={})
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    assert sub_obj.handle_submission(ctx, cfg) is None


def test_handle_submission_compute_revisions_fail() -> None:
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"I": "p:v"}}}}
    submissions_obj = _get_submissions_obj(test_config=test_config)
    sub = MockSubmission(compute_revisions_value=False, channels=[Repos("p", "v", "x86_64")])
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=submissions_obj.flavors["AAA"])
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    assert submissions_obj.handle_submission(ctx, cfg) is None


def test_handle_submission_revisions_fallback_none() -> None:
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"I": "p:v"}}}}
    submissions_obj = _get_submissions_obj(test_config=test_config)
    sub = MockSubmission(
        id=1,
        rrid="RRID",
        compute_revisions_value=True,
        rev_fallback_value=None,
        channels=[Repos("p", "v", "x86_64")],
    )
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=submissions_obj.flavors["AAA"])
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    assert submissions_obj.handle_submission(ctx, cfg) is None


def test_should_skip_embargoed(caplog: pytest.LogCaptureFixture, mocker: MockerFixture) -> None:
    caplog.set_level(logging.INFO)
    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {}}}}
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config=test_config,
        ),
        extrasettings=set(),
    )
    mocker.patch.object(submissions_obj, "filter_embargoed", return_value=True)
    sub = MockSubmission(id=1, rrid="RRID", revisions=None, channels=[], embargoed=True)
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data={})
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    assert submissions_obj.should_skip(ctx, cfg, {}) is True
    assert "Submission smelt:1 skipped: Embargoed and embargo-filtering enabled" in caplog.text


def test_should_skip_kernel_missing_repo(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    submissions_obj = Submissions(
        JobConfig(
            product="SLES",
            product_repo=None,
            product_version=None,
            settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
            config={"FLAVOR": {}},
        ),
        extrasettings=set(),
    )
    sub = MockSubmission(id=1, rrid="RRID", revisions=None, channels=[], livepatch=False)
    ctx = SubContext(sub=sub, arch="x86_64", flavor="Kernel-Default", data={})
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=False)
    matches = {"OTHER_ISSUE": [Repos("p", "v", "a")]}
    assert submissions_obj.should_skip(ctx, cfg, matches) is True
    assert "Kernel submission missing product repository" in caplog.text
    matches = {"OS_TEST_ISSUES": [Repos("p", "v", "a")]}
    assert submissions_obj.should_skip(ctx, cfg, matches) is False


@pytest.mark.parametrize(
    ("data", "matches", "expected", "log_msg"),
    [
        (
            {"aggregate_job": False, "aggregate_check_true": ["MATCH"]},
            {"MATCH", "OTHER"},
            False,
            "Submission smelt:1: Aggregate job not required",
        ),
        (
            {"aggregate_job": False, "aggregate_check_false": ["MISSING"]},
            {"OTHER"},
            False,
            "Submission smelt:1: Aggregate job not required",
        ),
        (
            {"aggregate_job": False, "aggregate_check_true": ["POS"], "aggregate_check_false": ["NEG"]},
            {"NEG"},
            True,
            None,
        ),
    ],
)
def test_is_aggregate_needed_logic(
    caplog: pytest.LogCaptureFixture, *, data: dict, matches: set, expected: bool, log_msg: str | None
) -> None:
    caplog.set_level(logging.INFO)
    submissions_obj = _get_submissions_obj(test_config={"FLAVOR": {}})
    sub = MockSubmission(id=1, rrid="RRID", revisions=None, channels=[])
    ctx = SubContext(sub=sub, arch="x86_64", flavor="AAA", data=data)
    assert submissions_obj.is_aggregate_needed(ctx, matches) is expected
    if log_msg:
        assert log_msg in caplog.text


def test_handle_submission_prevents_empty_incident_repo() -> None:
    arch, flavor, version = "x86_64", "Server-DVD-HA-Incidents", "15-SP7"
    config = {"FLAVOR": {flavor: {"archs": [arch], "issues": {"BASE_TEST_ISSUES": "SLE:any#15-SP7"}}}}
    subs = Submissions(JobConfig("SLE", None, "MISMATCH", {"VERSION": version, "DISTRI": "sle"}, config), set())

    sub = MockSubmission()
    sub.channels = [Repos("SLE", "any", arch, "15-SP7")]
    sub.revisions = {ArchVer(arch, "MISMATCH"): 12345}

    ctx = SubContext(sub, arch, flavor, subs.flavors[flavor])
    cfg = SubConfig(token={}, ci_url=None, ignore_onetime=True)

    res = subs.handle_submission(ctx, cfg)

    assert res is not None
    assert (
        res["openqa"]["INCIDENT_REPO"]
        == "http://%REPO_MIRROR_HOST%/ibs/SUSE:/Maintenance:/0/SUSE_Updates_SLE_any_x86_64"
    )
