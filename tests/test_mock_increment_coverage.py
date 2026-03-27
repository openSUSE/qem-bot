# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Tests for additional coverage in openqabot/types/increment.py."""

import pytest

from openqabot.types.increment import BuildInfo


def test_log_no_jobs_empty(caplog: pytest.LogCaptureFixture) -> None:
    """Test log_no_jobs with empty params."""
    caplog.set_level("INFO")
    info = BuildInfo("distri", "product", "version", "flavor", "arch", "build")
    info.log_no_jobs([])
    assert "Skipping approval: There are no relevant jobs on openQA for {}" in caplog.text
