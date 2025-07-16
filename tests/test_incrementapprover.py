from collections import namedtuple
from typing import Any, List
from urllib.parse import urlparse
import logging

from responses import GET, matchers
import osc.conf
import osc.core
import pytest
import responses

from openqabot import OBS_URL, OBS_GROUP
from openqabot.incrementapprover import IncrementApprover

# Fake Namespace for IncrementApprover initialization
_namespace = namedtuple(
    "Namespace",
    (
        "dry",
        "token",
        "openqa_instance",
        "accepted",
        "request_id",
        "obs_project",
        "distri",
        "version",
        "flavor",
    ),
)

# define fake data
ReviewState = namedtuple("ReviewState", ("state", "by_group"))
openqa_url = "http://openqa-instance/api/v1/isos/job_stats"


@pytest.fixture(scope="function")
def fake_no_jobs(request):
    responses.add(GET, openqa_url, json={})


@pytest.fixture(scope="function")
def fake_pending_jobs(request):
    responses.add(GET, openqa_url, json={"scheduled": {}, "running": {}})


@pytest.fixture(scope="function")
def fake_not_ok_jobs(request):
    responses.add(
        GET,
        openqa_url,
        json={"done": {"passed": {"job_ids": [20]}, "failed": {"job_ids": [21]}}},
    )


@pytest.fixture(scope="function")
def fake_ok_jobs(request):
    responses.add(
        GET,
        openqa_url,
        json={"done": {"passed": {"job_ids": [20]}, "softfailed": {"job_ids": [21]}}},
    )


def fake_osc_get_config(override_apiurl: str):
    assert override_apiurl == OBS_URL


def fake_get_request_list(
    url: str, project: str, req_state: List[str]
) -> List[osc.core.Request]:
    assert url == OBS_URL
    assert project == "OBS:PROJECT"
    req = osc.core.Request()
    req.reqid = 42
    req.state = "review"
    req.reviews = [ReviewState("review", OBS_GROUP)]
    return [req]


def fake_change_review_state(
    apiurl: str, reqid: str, newstate: str, by_group: str, message: str
):
    assert apiurl == OBS_URL
    assert reqid == "42"
    assert newstate == "accepted"
    assert by_group == OBS_GROUP
    assert message == "All 2 jobs on openQA have passed/softfailed"


def run_approver(caplog, monkeypatch):
    caplog.set_level(logging.DEBUG, logger="bot.increment_approver")
    monkeypatch.setattr(osc.core, "get_request_list", fake_get_request_list)
    monkeypatch.setattr(osc.core, "change_review_state", fake_change_review_state)
    monkeypatch.setattr(osc.conf, "get_config", fake_osc_get_config)
    args = _namespace(
        False,
        "not-secret",
        urlparse("http://openqa-instance"),
        True,
        None,
        "OBS:PROJECT",
        "sle",
        "15.99",
        "Online-Increments",
    )
    increment_approver = IncrementApprover(args)
    increment_approver()


@responses.activate
def test_no_openqa_jobs(caplog, fake_no_jobs, monkeypatch):
    run_approver(caplog, monkeypatch)
    messages = [x[-1] for x in caplog.record_tuples]
    assert (
        "Skipping approval, there are no relevant jobs on openQA for sle-15.99-Online-Increments"
        in messages
    )


@responses.activate
def test_pending_openqa_jobs(caplog, fake_pending_jobs, monkeypatch):
    run_approver(caplog, monkeypatch)
    messages = [x[-1] for x in caplog.record_tuples]
    assert (
        "Skipping approval, some jobs on openQA are in pending states (running, scheduled)"
        in messages
    )


@responses.activate
def test_not_ok_openqa_jobs(caplog, fake_not_ok_jobs, monkeypatch):
    run_approver(caplog, monkeypatch)
    last_message = [x[-1] for x in caplog.record_tuples][-1]
    assert "The following openQA jobs ended up with result 'failed'" in last_message
    assert "http://openqa-instance/tests/21" in last_message
    assert "http://openqa-instance/tests/20" not in last_message


@responses.activate
def test_only_ok_openqa_jobs(caplog, fake_ok_jobs, monkeypatch):
    run_approver(caplog, monkeypatch)
    last_message = [x[-1] for x in caplog.record_tuples][-1]
    assert "All 2 jobs on openQA have passed/softfailed" in last_message
