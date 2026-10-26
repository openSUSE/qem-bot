# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test SubmissionKey."""

from __future__ import annotations

import pytest

from openqabot.errors import SubmissionArgError
from openqabot.types.submission_key import SubmissionKey


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("git:SLFO:6189", SubmissionKey("git", "SLFO", 6189), id="simple-project"),
        pytest.param("git:products/SLFO:6189", SubmissionKey("git", "products/SLFO", 6189), id="project-with-slash"),
        pytest.param(
            "smelt:SUSE:Maintenance:42:42",
            SubmissionKey("smelt", "SUSE:Maintenance:42", 42),
            id="project-with-colons",
        ),
    ],
)
def test_parse(raw: str, expected: SubmissionKey) -> None:
    key = SubmissionKey.parse(raw)

    assert key == expected
    assert str(key) == raw


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        pytest.param("not-a-valid-submission", "Expected format", id="no-separator"),
        pytest.param("smelt:1", "Expected format", id="missing-project"),
        pytest.param(":SUSE:Maintenance:1", "Expected format", id="missing-type"),
        pytest.param("smelt::1", "Expected format", id="empty-project"),
        pytest.param("smelt:SUSE:Maintenance:", "Expected format", id="empty-id"),
        pytest.param("smelt:SUSE:Maintenance:abc", "must be numeric", id="non-numeric-id"),
        pytest.param("smelt:SUSE:Maintenance:\u00b2", "must be numeric", id="non-ascii-digit-id"),
        pytest.param("smelt:SUSE:Maintenance:0", "must be greater than zero", id="zero-id"),
    ],
)
def test_parse_invalid(raw: str, message: str) -> None:
    with pytest.raises(SubmissionArgError, match=message):
        SubmissionKey.parse(raw)


def test_gitea_key() -> None:
    assert SubmissionKey.gitea("products/SLFO", 124) == SubmissionKey("git", "products/SLFO", 124)


def test_from_submission_dict() -> None:
    submission = {"type": "git", "project": "products/SLFO", "number": 124, "packages": []}

    assert SubmissionKey.from_submission_dict(submission) == SubmissionKey.gitea("products/SLFO", 124)


def test_to_dashboard_params() -> None:
    key = SubmissionKey("smelt", "SUSE:Maintenance:42", 42)

    assert key.to_dashboard_params() == {"project": "SUSE:Maintenance:42", "type": "smelt"}
