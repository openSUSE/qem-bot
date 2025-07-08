from collections import namedtuple
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
import logging
import re

from responses import GET, matchers
import osc.conf
import osc.core
import pytest
import responses

from openqabot import QEM_DASHBOARD, OBS_URL
from openqabot.giteasync import GiteaSync
from openqabot.loader.gitea import read_utf8, read_json, read_xml
import openqabot.loader.gitea

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
    host = "https://src.suse.de"
    pulls_url = urljoin(host, "api/v1/repos/products/SLFO/pulls")
    issues_url = urljoin(host, "api/v1/repos/products/SLFO/issues")
    patchinfo_path = "products/SLFO/raw/commit/2cf58b3a9c32d139470a5f32d5aa64efbd0fa90dda0144b09421709252fcb0ea/patchinfo.23193048203482931/_patchinfo"
    patchinfo_data = Path("responses/patch-info.xml").read_bytes()
    responses.add(GET, pulls_url + "?state=open&page=1", json=read_json("pulls"))
    responses.add(GET, re.compile(pulls_url + r"\?state=open&page=.*"), json=[])
    responses.add(GET, pulls_url + "/124/reviews", json=read_json("reviews-124"))
    responses.add(GET, pulls_url + "/124/files", json=read_json("files-124"))
    responses.add(GET, re.compile(pulls_url + r"/.*/reviews"), json=[])
    responses.add(GET, re.compile(pulls_url + r"/.*/files"), json=[])
    responses.add(GET, issues_url + "/124/comments", json=read_json("comments-124"))
    responses.add(GET, re.compile(issues_url + r"/.*/comments"), json=[])
    responses.add(GET, urljoin(host, patchinfo_path), body=patchinfo_data)


@pytest.fixture(scope="function")
def fake_dashboard_replyback():
    def reply_callback(request):
        return (200, [], request.body)

    responses.add_callback(
        responses.PATCH,
        re.compile(f"{QEM_DASHBOARD}api/incidents"),
        callback=reply_callback,
        match=[matchers.query_param_matcher({"type": "git"})],
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


def fake_get_multibuild_data(obs_project: str):
    assert obs_project == "SUSE:SLFO:1.1.99:PullRequest:124:SLES"
    return read_utf8("_multibuild-124-" + obs_project + ".xml")


def run_gitea_sync(caplog, monkeypatch):
    caplog.set_level(logging.DEBUG, logger="bot.giteasync")
    caplog.set_level(logging.DEBUG, logger="bot.loader.gitea")
    monkeypatch.setattr(osc.core, "http_GET", fake_osc_http_get)
    monkeypatch.setattr(osc.util.xml, "xml_parse", fake_osc_xml_parse)
    monkeypatch.setattr(osc.conf, "get_config", fake_osc_get_config)
    monkeypatch.setattr(
        openqabot.loader.gitea, "get_multibuild_data", fake_get_multibuild_data
    )
    args = _namespace(False, False, "123", "456", False, "products/SLFO", True, False)
    assert GiteaSync(args)() == 0


@responses.activate
def test_sync_with_product_repo(
    caplog, fake_gitea_api, fake_dashboard_replyback, monkeypatch
):
    run_gitea_sync(caplog, monkeypatch)
    messages = [x[-1] for x in caplog.record_tuples]
    expected_repo = "SUSE:SLFO:1.1.99:PullRequest:124:SLES"
    assert "Relevant archs for " + expected_repo + ": ['aarch64', 'x86_64']" in messages
    assert "Loaded 7 active PRs/incidents from products/SLFO" in messages
    assert "Getting info about PR 131 from Gitea" in messages
    assert "Updating info about 1 incidents" in messages
    assert len(responses.calls) == 25
    assert len(responses.calls[-1].response.json()) == 1
    incident = responses.calls[-1].response.json()[0]
    assert incident["number"] == 124
    assert incident["packages"] == ["tree"]
    channels = incident["channels"]
    failed_or_unpublished = incident["failed_or_unpublished_packages"]
    for arch in ["aarch64", "x86_64"]:  # ppc64le skipped as not present in _multibuild
        channel = "#".join([":".join((expected_repo, arch)), "15.99"])
        assert channel in channels
        assert channel in failed_or_unpublished
    assert incident["project"] == "SLFO"
    assert incident["url"] == "https://src.suse.de/products/SLFO/pulls/124"
    assert incident["inReview"] == True
    assert incident["inReviewQAM"] == True
    assert incident["isActive"] == True
    assert incident["approved"] == False
    assert incident["embargoed"] == False
    assert incident["priority"] == 0

    # expect the scminfo from the product repo of the configured product
    assert "18bfa2a23fb7985d5d0" in incident["scminfo"]
    assert "18bfa2a23fb7985d5d0" in incident["scminfo_SLES"]


@responses.activate
def test_sync_with_codestream_repo(
    caplog, fake_gitea_api, fake_dashboard_replyback, monkeypatch
):
    monkeypatch.setattr(openqabot.loader.gitea, "OBS_REPO_TYPE", "standard")
    monkeypatch.setattr(openqabot.loader.gitea, "OBS_PRODUCTS", "")
    run_gitea_sync(caplog, monkeypatch)

    # expect the codestream repo to be used
    expected_repo = "SUSE:SLFO:1.1.99:PullRequest:124"
    incident = responses.calls[-1].response.json()[0]
    channels = incident["channels"]
    failed_or_unpublished = incident["failed_or_unpublished_packages"]
    for arch in ["ppc64le", "aarch64", "x86_64"]:
        channel = ":".join((expected_repo, arch))
        assert channel in channels
        assert channel in failed_or_unpublished

    # expect the scminfo from the codestream repo
    assert "f229fea352e8f268960" in incident["scminfo"]
    assert "18bfa2a23fb7985d5d0" in incident["scminfo_SLES"]
