# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test aggregate sync."""

from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from openqabot.aggrsync import AggregateResultsSync
from openqabot.errors import FetchJobsError
from openqabot.types.types import Data


@pytest.fixture
def args(mocker: MockerFixture) -> MagicMock:
    args = mocker.Mock()
    args.configs = "configs"
    args.token = "token"
    args.dry = False
    return args


@pytest.fixture
def mock_read_products(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("openqabot.aggrsync.read_products")


@pytest.fixture
def mock_openqa_interface(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("openqabot.syncres.OpenQAInterface")


@pytest.mark.usefixtures("mock_openqa_interface")
def test_call(args: MagicMock, mock_read_products: MagicMock) -> None:
    mock_read_products.return_value = []
    sync = AggregateResultsSync(args)
    sync()


def test_call_with_results(
    args: MagicMock, mocker: MockerFixture, mock_read_products: MagicMock, mock_openqa_interface: MagicMock
) -> None:
    # Mock dependencies
    mock_read_products.return_value = ["product1"]
    mocker.patch(
        "openqabot.aggrsync.get_aggregate_settings_data",
        return_value=[mocker.Mock(spec=["settings_id"])],
    )

    mock_client = mock_openqa_interface.return_value
    mock_client.get_jobs.return_value = [{"id": 1, "group": "group", "clone_id": None, "result": "passed"}]

    sync = AggregateResultsSync(args)

    # Mock methods from base class SyncRes
    mocker.patch.object(sync, "filter_jobs", return_value=True)
    mocker.patch.object(sync, "normalize_data_safe", return_value={"job_id": 1, "status": "passed"})
    mock_post_result = mocker.patch.object(sync, "post_result")

    sync()

    mock_post_result.assert_called_once()


def test_aggregate_fetch_failure_names_product(
    args: MagicMock, mocker: MockerFixture, mock_read_products: MagicMock, mock_openqa_interface: MagicMock
) -> None:
    data = Data(0, "aggregate", 110, "Flavor", "x86_64", "linux", "15.5", "20260101-1", "ProductX")
    mock_read_products.return_value = ["ProductX"]
    mocker.patch("openqabot.aggrsync.get_aggregate_settings_data", return_value=[data])
    mock_client = mock_openqa_interface.return_value
    mock_client.get_jobs.side_effect = RuntimeError("Fetch failed")

    sync = AggregateResultsSync(args)
    with pytest.raises(FetchJobsError) as exc_info:
        sync()

    assert "aggregate ProductX settings 110 (linux 15.5 Flavor x86_64 build 20260101-1)" in str(exc_info.value)
    assert "Fetch failed" in str(exc_info.value)
