# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from typing import NamedTuple


class Repos(NamedTuple):
    product: str
    version: str
    arch: str
    product_version: str = ""  # if non-empty, "version" is the codestream version


class ProdVer(NamedTuple):
    product: str
    version: str
    product_version: str = ""  # if non-empty, "version" is the codestream version


class Data(NamedTuple):
    incident: int
    settings_id: int
    flavor: str
    arch: str
    distri: str
    version: str
    build: str
    product: str


class ArchVer(NamedTuple):
    arch: str
    version: str  # the product version (and not the codestream version) if present in the context ArchVer is used
