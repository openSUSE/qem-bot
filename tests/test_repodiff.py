# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import json
from typing import NamedTuple

import pytest

from openqabot.repodiff import RepoDiff


class Namespace(NamedTuple):
    dry: bool
    fake_data: bool
    repo_a: str
    repo_b: str


def test_repodiff(capsys: pytest.CaptureFixture[str]) -> None:
    RepoDiff(
        Namespace(
            dry=True,
            fake_data=True,
            repo_a="OBS:PROJECT:PUBLISH_product",
            repo_b="OBS:PROJECT:TEST_product",
        ),
    )()
    res = json.loads(capsys.readouterr().out)
    assert set(res.keys()) == {"aarch64", "ppc64le", "noarch"}


def test_repodiff_compression(capsys: pytest.CaptureFixture[str]) -> None:
    RepoDiff(
        Namespace(
            dry=True,
            fake_data=True,
            repo_a="OBS:PROJECT:PUBLISH_product_zst",
            repo_b="OBS:PROJECT:TEST_product_gz",
        ),
    )()
    res = json.loads(capsys.readouterr().out)
    assert set(res.keys()) == {"aarch64", "ppc64le", "noarch"}
