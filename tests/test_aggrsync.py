# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from pathlib import Path
from urllib.parse import urlparse
from unittest.mock import MagicMock, patch

from openqabot.aggrsync import AggregateResultsSync


@patch("openqabot.aggrsync.SyncRes.__init__")
@patch("openqabot.aggrsync.read_products")
def test_constructor(mock_products, mock_syncres):
    mock_products.return_value = "foo"
    args = Namespace(configs="bar")
    sync = AggregateResultsSync(args)
    assert sync.product == "foo"
    mock_products.assert_called_once_with("bar")
    mock_syncres.assert_called_once_with(args)


@patch("openqabot.aggrsync.SyncRes.__init__")
@patch("openqabot.aggrsync.read_products", return_value=[])
@patch("openqabot.aggrsync.get_aggregate_settings_data", return_value=[])
@patch("openqabot.aggrsync.SyncRes.post_result")
def test_call_no_settings(mock_post, mock_settings, mock_products, mock_syncres):
    args = Namespace(
        configs=Path("bar"),
        dry=True,
        token="null",
        instance="null",
        openqa_instance=urlparse("http://localhost"),
    )
    sync = AggregateResultsSync(args)
    assert sync() == 0
    mock_post.assert_not_called()
    mock_syncres.assert_called_once_with(args)


@patch("openqabot.aggrsync.read_products", return_value=["product"])
@patch("openqabot.aggrsync.get_aggregate_settings_data", return_value=["some_data"])
@patch("openqabot.aggrsync.SyncRes.filter_jobs", return_value=False)
@patch("openqabot.aggrsync.SyncRes.normalize_data")
@patch("openqabot.aggrsync.SyncRes.post_result")
def test_call_filter_jobs(mock_post, mock_normalize, mock_filter, mock_settings, mock_products):
    args = Namespace(
        configs=Path("bar"),
        dry=True,
        token="null",
        instance="null",
        openqa_instance=urlparse("http://localhost"),
    )
    sync = AggregateResultsSync(args)
    sync.client = MagicMock()
    sync.client.get_jobs.return_value = [{"id": 1}]
    assert sync() == 0
    mock_normalize.assert_not_called()
    mock_post.assert_not_called()
