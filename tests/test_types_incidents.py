# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from unittest.mock import patch

import requests

from openqabot.types import Repos
from openqabot.types.incident import Incident
from openqabot.types.incidents import IncConfig, IncContext, Incidents


def test_repo_osuse() -> None:
    # Test for "openSUSE-SLE"
    chan = Repos("openSUSE-SLE", "15.3", "x86_64", "")
    assert Incidents._repo_osuse(chan) == ("openSUSE-SLE", "15.3")  # noqa: SLF001

    # Test for other products
    chan = Repos("SLES", "15-SP3", "s390x", "")
    assert Incidents._repo_osuse(chan) == ("SLES", "15-SP3", "s390x")  # noqa: SLF001


def test_is_scheduled_job_exception() -> None:
    inc_data = {
        "number": 123,
        "rr_number": 1,
        "project": "SUSE:Maintenance:123",
        "inReview": True,
        "isActive": True,
        "inReviewQAM": True,
        "approved": False,
        "embargoed": False,
        "packages": ["foo"],
        "channels": ["SUSE:Updates:SLE-Product-SLES:15-SP3:x86_64"],
        "emu": False,
    }
    inc = Incident(inc_data)
    with patch(
        "openqabot.types.incidents.retried_requests.get",
        side_effect=requests.exceptions.RequestException,
    ):
        assert not Incidents._is_scheduled_job(  # noqa: SLF001
            {}, inc, "x86_64", "15-SP3", "myflavor"
        )


def test_handle_incident_git_not_ongoing() -> None:
    inc_data = {
        "number": 123,
        "rr_number": 1,
        "project": "SUSE:Maintenance:123",
        "inReview": True,
        "isActive": False,
        "inReviewQAM": False,
        "approved": True,
        "embargoed": False,
        "packages": ["foo"],
        "channels": ["SUSE:Updates:SLE-Product-SLES:15-SP3:x86_64"],
        "emu": False,
        "type": "git",
    }
    inc = Incident(inc_data)
    # inc.ongoing is False now

    test_config = {"FLAVOR": {"AAA": {"archs": [""], "issues": {}}}}
    incidents_obj = Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "", "DISTRI": None},
        config=test_config,
        extrasettings=None,
    )

    ctx = IncContext(inc=inc, arch="", flavor="AAA", data={})
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)

    result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
    assert result is None


def test_handle_incident_embargoed() -> None:
    inc_data = {
        "number": 123,
        "rr_number": 1,
        "project": "SUSE:Maintenance:123",
        "inReview": True,
        "isActive": True,
        "inReviewQAM": True,
        "approved": False,
        "embargoed": True,
        "packages": ["foo"],
        "channels": ["SUSE:Updates:SLE-Product-SLES:15-SP3:x86_64"],
        "emu": False,
        "type": "smelt",
    }
    inc = Incident(inc_data)

    test_config = {"FLAVOR": {"AAA": {"archs": [""], "issues": {}}}}
    incidents_obj = Incidents(
        product="",
        product_repo=None,
        product_version=None,
        settings={"VERSION": "", "DISTRI": None, "FILTER_EMBARGOED": True},
        config=test_config,
        extrasettings=None,
    )

    ctx = IncContext(inc=inc, arch="", flavor="AAA", data={})
    cfg = IncConfig(token={}, ci_url=None, ignore_onetime=False)

    with patch("openqabot.types.incident.get_max_revision", return_value=123):
        result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001
        assert result is None


def test_handle_incident_with_ci_url() -> None:
    inc_data = {
        "number": 123,
        "rr_number": 1,
        "project": "SUSE:Maintenance:123",
        "inReview": True,
        "isActive": True,
        "inReviewQAM": True,
        "approved": False,
        "embargoed": False,
        "packages": ["foo"],
        "channels": ["SUSE:Updates:SLE-Product-SLES:15-SP3:x86_64"],
        "emu": False,
        "type": "smelt",
    }
    inc = Incident(inc_data)

    test_config = {"FLAVOR": {"AAA": {"archs": ["x86_64"], "issues": {"OS_TEST_ISSUES": "SLE-Product-SLES:15-SP3"}}}}
    incidents_obj = Incidents(
        product="SLES",
        product_repo="SLE-Product-SLES",
        product_version="15-SP3",
        settings={"VERSION": "15-SP3", "DISTRI": "SLES"},
        config=test_config,
        extrasettings=set(),
    )
    incidents_obj.singlearch = set()

    ctx = IncContext(inc=inc, arch="x86_64", flavor="AAA", data=incidents_obj.flavors["AAA"])
    cfg = IncConfig(token={}, ci_url="http://my-ci.com/123", ignore_onetime=True)

    with patch("openqabot.types.incident.get_max_revision", return_value=123):
        result = incidents_obj._handle_incident(ctx, cfg)  # noqa: SLF001

    assert result is not None
    assert result["openqa"]["__CI_JOB_URL"] == "http://my-ci.com/123"
