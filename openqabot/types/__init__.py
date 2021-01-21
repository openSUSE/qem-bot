from typing import NamedTuple

class Repos(NamedTuple):
    product: str
    version: str
    arch: str

class ProdVer(NamedTuple):
    product: str
    version: str
