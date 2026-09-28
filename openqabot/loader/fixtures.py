# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Response fixtures that the loaders read instead of querying a remote service."""

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=128)
def read_utf8(name: str) -> str:
    """Read a UTF-8 encoded response file."""
    return Path(f"tests/fixtures/responses/{name}").read_text(encoding="utf8")
