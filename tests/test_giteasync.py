from collections import namedtuple
import logging
from typing import Any
import re

import pytest
import responses
import osc.conf
import osc.core

from openqabot.loader.gitea import read_json, read_xml
from openqabot.giteasync import GiteaSync
from openqabot import QEM_DASHBOARD, OBS_URL

# Fake Namespace for GiteaSync initialization
_namespace = namedtuple(
    "Namespace",
    (
        "dry",
        "fake_data",
        "token",
        "gitea_token",
        "retry",
        "gitea_repo",
        "allow_build_failures",
        "consider_unrequested_prs",
    ),
)


@pytest.fixture(scope="function")
def fake_gitea_api(request):
    responses.add(
        responses.GET,
        "https://src.suse.de/api/v1/repos/products/SLFO/pulls?state=open&page=1",
        json=read_json("pulls"),
    )
    responses.add(
        responses.GET,
        re.compile(
            r"https://src.suse.de/api/v1/repos/products/SLFO/pulls\?state=open&page=.*"
        ),
        json=[],
    )
    responses.add(
        responses.GET,
        "https://src.suse.de/api/v1/repos/products/SLFO/pulls/124/reviews",
        json=read_json("reviews-124"),
    )
    responses.add(
        responses.GET,
        re.compile(r"https://src.suse.de/api/v1/repos/products/SLFO/pulls/.*/reviews"),
        json=[],
    )
    responses.add(
        responses.GET,
        "https://src.suse.de/api/v1/repos/products/SLFO/issues/124/comments",
        json=read_json("comments-124"),
    )
    responses.add(
        responses.GET,
        re.compile(
            r"https://src.suse.de/api/v1/repos/products/SLFO/issues/.*/comments"
        ),
        json=[],
    )


@pytest.fixture(scope="function")
def fake_dashboard_replyback():
    def reply_callback(request):
        return (200, [], request.body)

    responses.add_callback(
        responses.PATCH,
        re.compile(f"{QEM_DASHBOARD}api/incidents"),
        callback=reply_callback,
    )


def fake_osc_http_get(url: str):
    if url == "https://api.suse.de/build/SUSE:SLFO:1.1.99:PullRequest:124/_result":
        return read_xml("build-results-124-SUSE:SLFO:1.1.99:PullRequest:124")
    if url == "https://api.suse.de/build/SUSE:SLFO:1.1.99:PullRequest:124:SLES/_result":
        return read_xml("build-results-124-SUSE:SLFO:1.1.99:PullRequest:124:SLES")
    raise AssertionError("Code tried to query unexpected OSC URL: " + url)


def fake_osc_xml_parse(data: Any):
    return data  # fake_osc_http_get already returns parsed XML so just return that


def fake_osc_get_config(override_apiurl: str):
    assert override_apiurl == OBS_URL


@responses.activate
def test_sync(caplog, fake_gitea_api, fake_dashboard_replyback, monkeypatch):
    caplog.set_level(logging.DEBUG, logger="bot.giteasync")
    caplog.set_level(logging.DEBUG, logger="bot.loader.gitea")
    monkeypatch.setattr(osc.core, "http_GET", fake_osc_http_get)
    monkeypatch.setattr(osc.util.xml, "xml_parse", fake_osc_xml_parse)
    monkeypatch.setattr(osc.conf, "get_config", fake_osc_get_config)
    args = _namespace(False, False, "123", "456", False, "products/SLFO", True, False)
    assert GiteaSync(args)() == 0
    messages = [x[-1] for x in caplog.record_tuples]
    assert "Loaded 7 active PRs/incidents from products/SLFO" in messages
    assert "Getting info about PR 131 from Gitea" in messages
    assert "Updating info about 1 incidents" in messages
    assert len(responses.calls) == 17
    assert len(responses.calls[-1].response.json()) == 1
    incident = responses.calls[-1].response.json()[0]
    assert incident["number"] == 124
    assert incident["packages"] == ["gcc-15-image"]
    assert "SUSE:SLFO:1.1.99:PullRequest:124:SLES:x86_64" in incident["channels"]
    assert "SUSE:SLFO:1.1.99:PullRequest:124:SLES:aarch64" in incident["channels"]
    assert "SUSE:SLFO:1.1.99:PullRequest:124:SLES:ppc64le" in incident["channels"]
    assert incident["project"] == "SLFO"
    assert incident["url"] == "https://src.suse.de/products/SLFO/pulls/124"
    assert incident["inReview"] == True
    assert incident["inReviewQAM"] == True
    assert incident["isActive"] == True
    assert incident["approved"] == False
    assert incident["embargoed"] == False
    assert incident["priority"] == 0
    assert (
        incident["scminfo"]
        == "18bfa2a23fb7985d5d0cc356474a96a19d91d2d8652442badf7f13bc07cd1f3d"
    )
