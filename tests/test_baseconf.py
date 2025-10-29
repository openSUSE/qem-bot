# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

import pytest

from openqabot.types.baseconf import BaseConf, Incident


class FakeBaseConf(BaseConf):
    def __call__(
        self,
        _incidents: list[Incident],
        _token: dict[str, str],
        _ci_url: str | None,
        *,
        _ignore_onetime: bool,
    ) -> list[dict[str, Any]]:
        return [{"foo": "bar"}]

    @staticmethod
    def normalize_repos(_config: Any) -> None:
        pass


prod_name = "prod"
settings = {"PUBLIC_CLOUD_SOMETHING": "1"}


@pytest.fixture
def baseconf_gen() -> FakeBaseConf:
    return FakeBaseConf(prod_name, None, None, settings, {})


def test_baseconf_init(baseconf_gen: FakeBaseConf) -> None:
    assert baseconf_gen.product == prod_name
    assert baseconf_gen.settings == settings


def test_is_embargoed(baseconf_gen: FakeBaseConf) -> None:
    assert baseconf_gen.filter_embargoed("None")

    baseconf_gen.settings["PUBLIC_CLOUD_SOMETHING"] = ""

    assert baseconf_gen.filter_embargoed("None")

    baseconf_gen.settings = {}

    assert baseconf_gen.filter_embargoed("Noone") is False
    assert baseconf_gen.filter_embargoed("Azure-test")
