# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from pytest_mock import MockerFixture

import openqabot.args


def test_do_full_schedule(mocker: MockerFixture) -> None:
    bot = mocker.patch("openqabot.openqabot.OpenQABot")
    args = mocker.Mock()
    openqabot.args.do_full_schedule(args)
    bot.assert_called_once_with(args)
    assert not args.disable_aggregates
