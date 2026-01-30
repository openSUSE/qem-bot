# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test approve git."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from openqabot.approver import Approver
from openqabot.loader.qem import SubReq

from .helpers import args

if TYPE_CHECKING:
    import pytest


def test_git_approve_no_url(caplog: pytest.LogCaptureFixture) -> None:
    approver_instance = Approver(args)
    sub = SubReq(sub=1, req=100, type="git", url=None)
    caplog.set_level(logging.ERROR)
    assert not approver_instance.git_approve(sub, "msg")
    assert "Gitea API error: PR 1 has no URL" in caplog.text
