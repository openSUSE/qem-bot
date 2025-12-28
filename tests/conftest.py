# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import pytest

from openqabot.dashboard import clear_cache


@pytest.fixture(autouse=True)
def _auto_clear_cache() -> None:
    clear_cache()
