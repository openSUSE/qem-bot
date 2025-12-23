# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from pytest_mock import MockerFixture

from openqabot.aggrsync import AggregateResultsSync


def test_call(mocker: MockerFixture) -> None:
    args = mocker.Mock()
    mocker.patch("openqabot.syncres.openQAInterface")
    mocker.patch("openqabot.aggrsync.read_products", return_value=[])
    sync = AggregateResultsSync(args)
    sync()


def test_call_with_results(mocker: MockerFixture) -> None:
    args = mocker.Mock()
    args.configs = "configs"
    args.token = "token"  # noqa: S105
    args.dry = False

    # Mock dependencies
    mocker.patch("openqabot.aggrsync.read_products", return_value=["product1"])
    mocker.patch(
        "openqabot.aggrsync.get_aggregate_settings_data",
        return_value=[mocker.Mock(spec=["settings_id"])],
    )

    mock_client = mocker.patch("openqabot.syncres.openQAInterface").return_value
    mock_client.get_jobs.return_value = [{"id": 1, "group": "group", "clone_id": None, "result": "passed"}]

    sync = AggregateResultsSync(args)

    # Mock methods from base class SyncRes
    mocker.patch.object(sync, "filter_jobs", return_value=True)
    mocker.patch.object(sync, "_normalize_data", return_value={"job_id": 1, "status": "passed"})
    mock_post_result = mocker.patch.object(sync, "post_result")

    sync()

    mock_post_result.assert_called_once()
