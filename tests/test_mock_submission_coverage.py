# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from .fixtures.submissions import MockSubmission


def test_mock_submission_revisions_fallback_none() -> None:
    # Coverage for line 44 in tests/fixtures/submissions.py
    sub = MockSubmission(revisions=None)
    assert sub.revisions_with_fallback("arch", "ver") is None


def test_mock_submission_contains_package_none() -> None:
    # Coverage for line 49 in tests/fixtures/submissions.py
    sub = MockSubmission(packages=["pkg1"])
    assert sub.contains_package(["pkg1"]) is True
    assert sub.contains_package(["other"]) is False
