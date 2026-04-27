# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Tests for increment type definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openqabot.types.increment import BuildIdentifier, BuildInfo

if TYPE_CHECKING:
    import pytest
    from pytest_mock import MockerFixture


def test_build_identifier_from_job() -> None:
    job = {"build": "123", "distri": "sle", "version": "15-SP3"}
    bi = BuildIdentifier.from_job(job)
    assert bi.build == "123"
    assert bi.distri == "sle"
    assert bi.version == "15-SP3"


def test_build_identifier_from_params() -> None:
    params = {"BUILD": "123", "DISTRI": "sle", "VERSION": "15-SP3"}
    bi = BuildIdentifier.from_params(params)
    assert bi.build == "123"
    assert bi.distri == "sle"
    assert bi.version == "15-SP3"


def test_build_identifier_badge_params(mocker: MockerFixture) -> None:
    mocker.patch("openqabot.config.settings.allow_development_groups", None)
    bi = BuildIdentifier("123", "sle", "15-SP3")
    params = bi.get_base_badge_params()
    assert params["build"] == "123"
    assert params["not_group_glob"] == "*Devel*,*Test*"


def test_build_info_str() -> None:
    info = BuildInfo("sle", "SLES", "15-SP3", "Flavor", "x86_64", "123")
    assert str(info) == "SLESv15-SP3 build 123@x86_64 of flavor Flavor"


def test_build_info_string_with_params() -> None:
    info = BuildInfo("sle", "SLES", "15-SP3", "Flavor", "x86_64", "123")
    params = {"VERSION": "15-SP4", "BUILD": "456"}
    res = info.string_with_params(params)
    assert res == "SLESv15-SP4 build 456@x86_64 of flavor Flavor"


def test_build_info_format_multi_build() -> None:
    info = BuildInfo("sle", "SLES", "15-SP3", "Flavor", "x86_64", "123")
    assert info.format_multi_build([]) == "{}"
    params = [{"BUILD": "1"}]
    assert info.format_multi_build(params) == "SLESv15-SP3 build 1@x86_64 of flavor Flavor"
    params = [{"BUILD": "1"}, {"BUILD": "2"}]
    res = info.format_multi_build(params)
    assert "build 1" in res
    assert "build 2" in res


def test_log_no_jobs_empty(caplog: pytest.LogCaptureFixture) -> None:
    """Test log_no_jobs with empty params."""
    caplog.set_level("INFO")
    info = BuildInfo("distri", "product", "version", "flavor", "arch", "build")
    info.log_no_jobs([])
    assert "Skipping approval: There are no relevant jobs on openQA for {}" in caplog.text


def test_log_pending_jobs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO")
    info = BuildInfo("sle", "SLES", "15-SP3", "Flavor", "x86_64", "123")
    info.log_pending_jobs({"scheduled", "running"})
    assert "pending states (running, scheduled)" in caplog.text
