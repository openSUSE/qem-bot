# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from typing import Any, Dict, List, Optional

import pytest

from openqabot.types.baseconf import BaseConf, Incident


class FakeBaseConf(BaseConf):
    def __call__(
        self,
        _incidents: List[Incident],
        _token: Dict[str, str],
        _ci_url: Optional[str],
        _ignore_onetime: bool,
    ) -> List[Dict[str, Any]]:
        return [{"foo": "bar"}]

    @staticmethod
    def normalize_repos(_config):
        pass


prod_name = "prod"
settings = {"PUBLIC_CLOUD_SOMETHING": "1"}


@pytest.fixture
def baseconf_gen():
    return FakeBaseConf(prod_name, None, None, settings, {})


def test_baseconf_init(baseconf_gen):
    assert baseconf_gen.product == prod_name
    assert baseconf_gen.settings == settings


def test_is_embargoed(baseconf_gen):
    assert baseconf_gen.filter_embargoed("None")

    baseconf_gen.settings["PUBLIC_CLOUD_SOMETHING"] = ""

    assert baseconf_gen.filter_embargoed("None")

    baseconf_gen.settings = {}

    assert baseconf_gen.filter_embargoed("Noone") is False
    assert baseconf_gen.filter_embargoed("Azure-test")
