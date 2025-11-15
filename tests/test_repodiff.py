# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import json
from collections import namedtuple

import pytest

from openqabot.repodiff import RepoDiff

_namespace = namedtuple("Namespace", ("dry", "fake_data", "repo_a", "repo_b"))


def test_repodiff(capsys: pytest.CaptureFixture[str]) -> None:
    RepoDiff(
        _namespace(
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
        _namespace(
            dry=True,
            fake_data=True,
            repo_a="OBS:PROJECT:PUBLISH_product_zst",
            repo_b="OBS:PROJECT:TEST_product_gz",
        ),
    )()
    res = json.loads(capsys.readouterr().out)
    assert set(res.keys()) == {"aarch64", "ppc64le", "noarch"}
