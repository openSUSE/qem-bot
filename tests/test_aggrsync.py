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
