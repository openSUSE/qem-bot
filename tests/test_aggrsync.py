# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from unittest.mock import MagicMock
from urllib.parse import urlparse

import pytest
from pytest_mock import MockerFixture

from openqabot.aggrsync import AggregateResultsSync


@pytest.fixture
def args(mocker: MockerFixture) -> MagicMock:
    args = mocker.Mock()
    args.configs = "configs"
    args.token = "token"  # noqa: S105
    args.dry = False
    args.openqa_instance = urlparse("http://instance.qa")
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
    mocker.patch.object(sync, "_normalize_data", return_value={"job_id": 1, "status": "passed"})
    mock_post_result = mocker.patch.object(sync, "post_result")

    sync()

    mock_post_result.assert_called_once()
