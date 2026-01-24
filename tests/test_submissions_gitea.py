# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import responses
from openqabot.types.baseconf import JobConfig
from openqabot.types.submissions import Submissions
from openqabot.types.types import ArchVer, Repos

from .fixtures.submissions import MockSubmission


def _assert_gitea_settings(
    result: dict,
    *,
    arch: str,
    flavor: str,
    sub_id: int,
    sub_type: str,
    product_ver: str,
    repo_hash: int,
    expected_repo: str,
    distri: str,
) -> None:
    qem = result["qem"]
    assert qem["arch"] == arch
    assert qem["flavor"] == flavor
    assert qem["incident"] == sub_id
    assert qem["version"] == product_ver
    assert qem["withAggregate"]

    expected_settings = {
        "ARCH": arch,
        "BASE_TEST_ISSUES": str(sub_id),
        "BUILD": f":{sub_type}:{sub_id}:pkg",
        "DISTRI": distri,
        "FLAVOR": flavor,
        "INCIDENT_ID": sub_id,
        "INCIDENT_REPO": f"{expected_repo}-{arch}/",
        "REPOHASH": repo_hash,
        "VERSION": product_ver,
    }

    for s in [result["openqa"], qem["settings"]]:
        actual = {k: s[k] for k in expected_settings}
        assert actual == expected_settings


@responses.activate
def test_gitea_submissions() -> None:
    # declare fields of Repos used in this test
    product = "SUSE:SLFO"  # "product" is used to store the name of the codestream in Gitea-based submissions …
    version = "1.1.99:PullRequest:166:SLES"  # … and version is the full project including the product
    archs = ["x86_64", "aarch64"]
    product_ver = "15.99"

    # declare meta-data
    settings = {"VERSION": product_ver, "DISTRI": "sles"}
    issues = {"BASE_TEST_ISSUES": "SLFO:1.1.99#15.99"}
    flavor = "AAA"
    test_config = {"FLAVOR": {flavor: {"archs": archs, "issues": issues}}}

    # create a Git-based submission
    sub = MockSubmission(type="git")
    sub.id = 42
    repo_hash = 12345
    sub.channels = [Repos(product, version, arch, product_ver) for arch in archs]
    sub.revisions = {ArchVer(arch, product_ver): repo_hash for arch in archs}

    # compute openQA/dashboard settings for submission and check results
    subs = Submissions(JobConfig("SLFO", None, None, settings, test_config), set())
    subs.singlearch = set()
    expected_repo = "http://%REPO_MIRROR_HOST%/ibs/SUSE:/SLFO:/1.1.99:/PullRequest:/166:/SLES/product/repo/SLES-15.99"
    res = subs(submissions=[sub], token={}, ci_url="", ignore_onetime=False)
    assert len(res) == len(archs)
    for arch, result in zip(archs, res):
        _assert_gitea_settings(
            result,
            arch=arch,
            flavor=flavor,
            sub_id=sub.id,
            sub_type=sub.type,
            product_ver=product_ver,
            repo_hash=repo_hash,
            expected_repo=expected_repo,
            distri=settings["DISTRI"],
        )
