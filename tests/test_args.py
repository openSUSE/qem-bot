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


def test_do_submission_schedule(mocker: MockerFixture) -> None:
    bot = mocker.patch("openqabot.openqabot.OpenQABot")
    args = mocker.Mock()
    openqabot.args.do_submission_schedule(args)
    bot.assert_called_once_with(args)
    assert args.disable_aggregates


def test_do_aggregate_schedule(mocker: MockerFixture) -> None:
    bot = mocker.patch("openqabot.openqabot.OpenQABot")
    args = mocker.Mock()
    openqabot.args.do_aggregate_schedule(args)
    bot.assert_called_once_with(args)
    assert not args.disable_aggregates


def test_do_sync_smelt(mocker: MockerFixture) -> None:
    smeltsync = mocker.patch("openqabot.smeltsync.SMELTSync")
    args = mocker.Mock()
    openqabot.args.do_sync_smelt(args)
    smeltsync.assert_called_once_with(args)


def test_do_sync_gitea(mocker: MockerFixture) -> None:
    giteasync = mocker.patch("openqabot.giteasync.GiteaSync")
    args = mocker.Mock()
    openqabot.args.do_sync_gitea(args)
    giteasync.assert_called_once_with(args)


def test_do_approve(mocker: MockerFixture) -> None:
    approver = mocker.patch("openqabot.approver.Approver")
    args = mocker.Mock()
    openqabot.args.do_approve(args)
    approver.assert_called_once_with(args)


def test_do_comment(mocker: MockerFixture) -> None:
    commenter = mocker.patch("openqabot.commenter.Commenter")
    args = mocker.Mock()
    openqabot.args.do_comment(args)
    commenter.assert_called_once_with(args)


def test_do_sync_sub_results(mocker: MockerFixture) -> None:
    syncer = mocker.patch("openqabot.subsyncres.SubResultsSync")
    args = mocker.Mock()
    openqabot.args.do_sync_sub_results(args)
    syncer.assert_called_once_with(args)


def test_do_sync_aggregate_results(mocker: MockerFixture) -> None:
    syncer = mocker.patch("openqabot.aggrsync.AggregateResultsSync")
    args = mocker.Mock()
    openqabot.args.do_sync_aggregate_results(args)
    syncer.assert_called_once_with(args)


def test_do_increment_approve(mocker: MockerFixture) -> None:
    approve = mocker.patch("openqabot.incrementapprover.IncrementApprover")
    args = mocker.Mock()
    openqabot.args.do_increment_approve(args)
    approve.assert_called_once_with(args)


def test_do_repo_diff_computation(mocker: MockerFixture) -> None:
    repo_diff = mocker.patch("openqabot.repodiff.RepoDiff")
    args = mocker.Mock()
    openqabot.args.do_repo_diff_computation(args)
    repo_diff.assert_called_once_with(args)


def test_do_amqp(mocker: MockerFixture) -> None:
    amqp = mocker.patch("openqabot.amqp.AMQP")
    args = mocker.Mock()
    openqabot.args.do_amqp(args)
    amqp.assert_called_once_with(args)
