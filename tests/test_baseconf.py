# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

import pytest

from openqabot.types.baseconf import BaseConf, Incident


class FakeBaseConf(BaseConf):
    def __call__(
        self,
        incidents: list[Incident],  # noqa: ARG002
        token: dict[str, str],  # noqa: ARG002
        ci_url: str | None,  # noqa: ARG002
        *,
        ignore_onetime: bool,  # noqa: ARG002
    ) -> list[dict[str, Any]]:
        return [{"foo": "bar"}]

    @staticmethod
    def normalize_repos(config: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG004
        return {}


prod_name = "prod"
settings = {"PUBLIC_CLOUD_SOMETHING": "1"}


@pytest.fixture
def baseconf_gen() -> FakeBaseConf:
    return FakeBaseConf(prod_name, None, None, settings, {})


def test_baseconf_init(baseconf_gen: FakeBaseConf) -> None:
    assert baseconf_gen.product == prod_name
    assert baseconf_gen.settings == settings
    assert baseconf_gen([], {}, None, ignore_onetime=False), "can be called"
    assert not baseconf_gen.normalize_repos([]), "static method can be called"


def test_is_embargoed(baseconf_gen: FakeBaseConf) -> None:
    assert baseconf_gen.filter_embargoed("None")

    baseconf_gen.settings["PUBLIC_CLOUD_SOMETHING"] = ""

    assert baseconf_gen.filter_embargoed("None")

    baseconf_gen.settings = {}

    assert baseconf_gen.filter_embargoed("Noone") is False
    assert baseconf_gen.filter_embargoed("Azure-test")
