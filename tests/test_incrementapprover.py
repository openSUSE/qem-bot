from collections import namedtuple
from typing import Any, List
from urllib.parse import urlparse
import logging

from responses import GET, matchers
import osc.conf
import osc.core
import pytest
import responses

import openqabot
from openqabot.openqa import openQAInterface
from openqabot import OBS_URL, OBS_DOWNLOAD_URL, OBS_GROUP
from openqabot.loader.gitea import read_json
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
        "schedule",
        "reschedule",
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


@pytest.fixture(scope="function")
def fake_product_repo(request):
    responses.add(
        GET,
        OBS_DOWNLOAD_URL + "/OBS:/PROJECT/product/?jsontable=1",
        json=read_json("test-product-repo"),
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


def run_approver(caplog, monkeypatch, schedule: bool = False):
    jobs = []
    caplog.set_level(logging.DEBUG, logger="bot.increment_approver")
    monkeypatch.setattr(osc.core, "get_request_list", fake_get_request_list)
    monkeypatch.setattr(osc.core, "change_review_state", fake_change_review_state)
    monkeypatch.setattr(osc.conf, "get_config", fake_osc_get_config)
    monkeypatch.setattr(
        openqabot.openqa.openQAInterface,
        "post_job",
        lambda self, data: jobs.append(data),
    )
    args = _namespace(
        False,
        "not-secret",
        urlparse("http://openqa-instance"),
        True,
        None,
        "OBS:PROJECT",
        "sle",
        "16.0",
        "Online-Increments",
        schedule,
        False,
    )
    increment_approver = IncrementApprover(args)
    errors = increment_approver()
    return (errors, jobs)


@responses.activate
def test_skipping_with_no_openqa_jobs(
    caplog, fake_no_jobs, fake_product_repo, monkeypatch
):
    run_approver(caplog, monkeypatch)
    messages = [x[-1] for x in caplog.record_tuples]
    assert (
        "Skipping approval, there are no relevant jobs on openQA for SLESv16.0 build 139.1@aarch64 of flavor Online-Increments"
        in messages
    )


@responses.activate
def test_scheduling_with_no_openqa_jobs(
    caplog, fake_no_jobs, fake_product_repo, monkeypatch
):
    (errors, jobs) = run_approver(caplog, monkeypatch, schedule=True)
    messages = [x[-1] for x in caplog.record_tuples]
    assert (
        "Skipping approval, there are no relevant jobs on openQA for SLESv16.0 build 139.1@aarch64 of flavor Online-Increments"
        in messages
    )
    assert errors == 0, "no errors"
    for arch in ["x86_64", "aarch64", "ppc64le", "s390x"]:
        assert {
            "DISTRI": "sle",
            "VERSION": "16.0",
            "FLAVOR": "Online-Increments",
            "BUILD": "139.1",
            "ARCH": arch,
        } in jobs, f"{arch} jobs created"


@responses.activate
def test_skipping_with_pending_openqa_jobs(
    caplog, fake_pending_jobs, fake_product_repo, monkeypatch
):
    run_approver(caplog, monkeypatch)
    messages = [x[-1] for x in caplog.record_tuples]
    assert (
        "Skipping approval, some jobs on openQA for SLESv16.0 build 139.1@aarch64 of flavor Online-Increments are in pending states (running, scheduled)"
        in messages
    )


@responses.activate
def test_listing_not_ok_openqa_jobs(
    caplog, fake_not_ok_jobs, fake_product_repo, monkeypatch
):
    run_approver(caplog, monkeypatch)
    last_message = [x[-1] for x in caplog.record_tuples][-1]
    assert "The following openQA jobs ended up with result 'failed'" in last_message
    assert "http://openqa-instance/tests/21" in last_message
    assert "http://openqa-instance/tests/20" not in last_message


@responses.activate
def test_approval_if_there_are_only_ok_openqa_jobs(
    caplog, fake_ok_jobs, fake_product_repo, monkeypatch
):
    run_approver(caplog, monkeypatch)
    last_message = [x[-1] for x in caplog.record_tuples][-1]
    assert "All 2 jobs on openQA have passed/softfailed" in last_message
