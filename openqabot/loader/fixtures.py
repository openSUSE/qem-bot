# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Response fixtures that the loaders read instead of querying a remote service."""

from functools import lru_cache
from io import BytesIO
from pathlib import Path

from lxml import etree  # ty: ignore[unresolved-import]


@lru_cache(maxsize=128)
def read_utf8(name: str) -> str:
    """Read a UTF-8 encoded response file."""
    return Path(f"tests/fixtures/responses/{name}").read_text(encoding="utf8")


@lru_cache(maxsize=128)
def read_xml(name: str) -> etree.ElementTree:
    """Read an XML response file."""
    return etree.parse(BytesIO(read_utf8(name + ".xml").encode("utf-8")))
