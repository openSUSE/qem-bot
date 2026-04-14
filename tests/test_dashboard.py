# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test dashboard API client."""

from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from openqabot import dashboard
from openqabot.config import settings


@pytest.fixture(autouse=True)
def clear_dashboard_cache() -> None:
    """Ensure cache is empty before each test."""
    dashboard.clear_cache()


def test_get_json_basic(mocker: MockerFixture) -> None:
    mock_get = mocker.patch("openqabot.dashboard.retried_requests.get")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"foo": "bar"}
    mock_get.return_value = mock_resp

    res = dashboard.get_json("api/test")

    assert res == {"foo": "bar"}
    mock_get.assert_called_once_with(settings.qem_dashboard_url + "api/test", headers=settings.dashboard_token_dict)


def test_get_json_with_params_and_verify(mocker: MockerFixture) -> None:
    mock_get = mocker.patch("openqabot.dashboard.retried_requests.get")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"foo": "bar"}
    mock_get.return_value = mock_resp

    params = {"a": 1}
    res = dashboard.get_json("api/test", params=params, verify=False)

    assert res == {"foo": "bar"}
    mock_get.assert_called_once_with(
        settings.qem_dashboard_url + "api/test", headers=settings.dashboard_token_dict, params=params, verify=False
    )


def test_get_json_caching(mocker: MockerFixture) -> None:
    mock_get = mocker.patch("openqabot.dashboard.retried_requests.get")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"foo": "bar"}
    mock_get.return_value = mock_resp

    # First call
    res1 = dashboard.get_json("api/test")
    # Second call
    res2 = dashboard.get_json("api/test")

    assert res1 == res2 == {"foo": "bar"}
    assert mock_get.call_count == 1


def test_patch(mocker: MockerFixture) -> None:
    mock_patch = mocker.patch("openqabot.dashboard.retried_requests.patch")
    dashboard.patch("api/test", json={"foo": "bar"})
    mock_patch.assert_called_once_with(settings.qem_dashboard_url + "api/test", json={"foo": "bar"})


def test_put(mocker: MockerFixture) -> None:
    mock_put = mocker.patch("openqabot.dashboard.retried_requests.put")
    dashboard.put("api/test", json={"foo": "bar"})
    mock_put.assert_called_once_with(settings.qem_dashboard_url + "api/test", json={"foo": "bar"})
