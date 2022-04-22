# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from typing import NamedTuple


class Repos(NamedTuple):
    product: str
    version: str
    arch: str


class ProdVer(NamedTuple):
    product: str
    version: str


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
    version: str
