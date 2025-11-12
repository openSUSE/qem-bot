# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import json
import logging
from collections import namedtuple
from urllib.parse import urlparse

from _pytest.logging import LogCaptureFixture

import responses
from openqabot import QEM_DASHBOARD
from openqabot.amqp import AMQP

# Check fixtures in tests/fixtures/qembot_mocks.py
# imported from conftest.py

namespace = namedtuple("Namespace", ["dry", "token", "openqa_instance", "url", "gitea_token"])
args = namespace(True, "ToKeN", urlparse("http://instance.qa"), None, None)
amqp = AMQP(args)

fake_method = namedtuple("Method", ["routing_key"])
fake_job_done = fake_method("suse.openqa.job.done")
fake_review_request_topic = fake_method("suse.src.pull_request_review_request.review_requested")


@responses.activate
def test_handling_incident(caplog: LogCaptureFixture) -> None:
    # define response for get_incident_settings_data
    data = [
        {
            "id": 110,
            "flavor": "FakeFlavor",
            "arch": "arch",
            "settings": {"DISTRI": "linux", "BUILD": "33222"},
            "version": "13.3",
            "withAggregate": False,
        }
    ]
    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/incident_settings/33222",
        json=data,
    )

    # define response for get_aggregate_settings
    data = [
        {
            "id": 110,
            "flavor": "FakeFlavor",
            "arch": "arch",
            "settings": {"DISTRI": "linux", "BUILD": "33222"},
            "version": "13.3",
            "build": "33222",
        }
    ]
    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/update_settings/33222",
        json=data,
    )

    # define response for get_jobs
    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/jobs/incident/110",
        json=[{"incident_settings": 1000, "job_id": 110, "status": "passed"}],
    )

    # define incident
    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/incidents/33222",
        json={"number": 33222, "rr_number": 42},
    )

    caplog.set_level(logging.DEBUG)
    amqp.on_job_message("", fake_job_done, "", json.dumps({"BUILD": ":33222:emacs"}).encode("utf-8"))

    messages = [x[-1] for x in caplog.record_tuples]
    assert any('suse.openqa.job.done - {"BUILD": ":33222:emacs"}' in msg.strip() for msg in messages)
    assert any("Incidents to approve:" in msg.strip() for msg in messages)
    assert any("* SUSE:Maintenance:33222:42" in msg.strip() for msg in messages)


@responses.activate
def test_handling_aggregate(caplog: LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    amqp.on_job_message("", fake_job_done, "", json.dumps({"BUILD": "12345678-9"}).encode("utf-8"))

    messages = [x[-1] for x in caplog.record_tuples]
    assert any('suse.openqa.job.done - {"BUILD": "12345678-9"}' in msg.strip() for msg in messages)  # currently noop


@responses.activate
def test_handle_inc_review_request_triggers_scheduling(
    caplog: LogCaptureFixture,
    mock_incident_settings_from_pr160: callable,
    mock_incident_make_incident_from_pr: callable,
    mock_openqa_post_job: callable,
    mock_gitea_review_request_body: callable,
) -> None:
    caplog.set_level(logging.DEBUG)

    pr_number = 160
    body = mock_gitea_review_request_body(pr_number)
    args_no_dry = namespace(False, "ToKeN", urlparse("http://instance.qa"), None, None)
    amqp = AMQP(args_no_dry)

    mock_incident_make_incident_from_pr.return_value = mock_incident_settings_from_pr160

    with mock_openqa_post_job(amqp) as mock_post:
        amqp.on_review_request("", fake_review_request_topic, "", body)
        mock_incident_make_incident_from_pr.assert_called_once()
        call_kwargs = mock_incident_make_incident_from_pr.call_args[1]
        assert call_kwargs["dry"] is False, f"Expected dry=False, got dry={call_kwargs.get('dry')}"

        assert mock_post.call_count == 3, f"Expected 3 calls to post_job, got {mock_post.call_count}"
        expected_calls = [
            {
                "DISTRI": "sle",
                "VERSION": "15-SP4",
                "FLAVOR": "Server-DVD-Updates",
                "ARCH": "x86_64",
                "BUILD": ":160:some",
                "INCIDENT_ID": 160,
            },
            {
                "DISTRI": "sle",
                "VERSION": "15-SP4",
                "FLAVOR": "Server-DVD-Updates",
                "ARCH": "aarch64",
                "BUILD": ":160:some",
                "INCIDENT_ID": 160,
            },
            {
                "DISTRI": "sle",
                "VERSION": "15.4",
                "FLAVOR": "Server-DVD-Updates",
                "ARCH": "x86_64",
                "BUILD": ":160:some",
                "INCIDENT_ID": 160,
            },
        ]
        actual_calls = [call[0][0] for call in mock_post.call_args_list]
        assert actual_calls == expected_calls, f"Expected calls {expected_calls}, ****** got {actual_calls}"

    messages = [x[-1] for x in caplog.record_tuples]
    assert any("Received Gitea review request message" in m for m in messages)
    assert any("Scheduling jobs for PR 160" in m for m in messages)
    assert any("Scheduling jobs for PR 160 with 3 channel" in m for m in messages)
    assert any(
        "Review Request 160 with medium type variables is going to be scheduled in openQA" in m for m in messages
    )
    assert any("Successfully scheduled 3 jobs for PR 160" in m for m in messages)


@responses.activate
def test_smoke_handle_inc_review_request_dry_run(
    caplog: LogCaptureFixture,
    mock_incident_settings_from_pr160: callable,
    mock_incident_make_incident_from_pr: callable,
    mock_openqa_post_job: callable,
    mock_gitea_review_request_body: callable,
) -> None:
    caplog.set_level(logging.DEBUG)

    pr_number = 160
    body = mock_gitea_review_request_body(pr_number)

    mock_incident_make_incident_from_pr.return_value = mock_incident_settings_from_pr160
    with mock_openqa_post_job(amqp) as mock_post:
        amqp.on_review_request("", fake_review_request_topic, "", body)
        mock_incident_make_incident_from_pr.assert_called_once()
        mocked_data = mock_incident_make_incident_from_pr.call_args[1]
        assert mocked_data["dry"] is True
        mock_post.assert_not_called()

    messages = [x[-1] for x in caplog.record_tuples]
    assert any("Received Gitea review request message" in m for m in messages)
    assert any("Scheduling jobs for PR 160" in m for m in messages)
    assert any("Scheduling jobs for PR 160 with 3 channel" in m for m in messages)
    assert any(
        "Review Request 160 with medium type variables is going to be scheduled in openQA" in m for m in messages
    )
    assert any("Successfully scheduled 3 jobs for PR 160" in m for m in messages)
    assert any("Dry run - would schedule" in m for m in messages)


@responses.activate
def test_handle_inc_review_request_wrong_reviewer(
    caplog: LogCaptureFixture, mock_incident_make_incident_from_pr: callable, mock_gitea_review_request_body: callable
) -> None:
    caplog.set_level(logging.DEBUG)
    pr_number = 888
    body = mock_gitea_review_request_body(pr_number)

    args_test = namespace(False, "ToKeN", urlparse("http://instance.qa"), None, None)
    amqp = AMQP(args_test)

    amqp.on_review_request("", fake_review_request_topic, "", body)
    mock_incident_make_incident_from_pr.assert_not_called()

    messages = [x[-1] for x in caplog.record_tuples]
    assert any("Received Gitea review request message" in m for m in messages)
