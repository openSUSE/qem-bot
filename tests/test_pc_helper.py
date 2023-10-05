from unittest import mock
import re
import responses
from openqabot.pc_helper import (
    apply_pc_tools_image,
    apply_publiccloud_pint_image,
    get_latest_tools_image,
    get_recent_pint_image,
    apply_sles4sap_pint_image,
)
import openqabot.pc_helper


def test_apply_pc_tools_image(monkeypatch):
    known_return = "test"
    monkeypatch.setattr(
        openqabot.pc_helper,
        "get_latest_tools_image",
        lambda *args, **kwargs: known_return,
    )

    settings = {"PUBLIC_CLOUD_TOOLS_IMAGE_QUERY": "test"}
    apply_pc_tools_image(settings)
    assert "PUBLIC_CLOUD_TOOLS_IMAGE_BASE" in settings
    assert settings["PUBLIC_CLOUD_TOOLS_IMAGE_BASE"] == known_return
    assert "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY" not in settings


def test_apply_publiccloud_pint_image(monkeypatch):
    monkeypatch.setattr(
        openqabot.pc_helper, "pint_query", lambda *args, **kwargs: {"images": []}
    )
    monkeypatch.setattr(
        openqabot.pc_helper,
        "get_recent_pint_image",
        lambda *args, **kwargs: {"name": "test", "state": "active", "image_id": "111"},
    )
    settings = {}
    apply_publiccloud_pint_image(settings)
    assert settings["PUBLIC_CLOUD_IMAGE_ID"] is None
    assert "PUBLIC_CLOUD_PINT_QUERY" not in settings
    assert "PUBLIC_CLOUD_PINT_NAME" not in settings
    assert "PUBLIC_CLOUD_PINT_REGION" not in settings
    assert "PUBLIC_CLOUD_PINT_FIELD" not in settings
    assert "PUBLIC_CLOUD_REGION" not in settings

    settings = {
        "PUBLIC_CLOUD_PINT_QUERY": "test",
        "PUBLIC_CLOUD_PINT_NAME": "test",
        "PUBLIC_CLOUD_PINT_FIELD": "image_id",
    }
    apply_publiccloud_pint_image(settings)
    assert settings["PUBLIC_CLOUD_IMAGE_ID"] == "111"
    assert "PUBLIC_CLOUD_PINT_QUERY" not in settings
    assert "PUBLIC_CLOUD_PINT_NAME" not in settings
    assert "PUBLIC_CLOUD_PINT_REGION" not in settings
    assert "PUBLIC_CLOUD_PINT_FIELD" not in settings
    assert "PUBLIC_CLOUD_REGION" not in settings

    settings = {
        "PUBLIC_CLOUD_PINT_QUERY": "test",
        "PUBLIC_CLOUD_PINT_NAME": "test",
        "PUBLIC_CLOUD_PINT_FIELD": "image_id",
        "PUBLIC_CLOUD_PINT_REGION": "south",
    }
    apply_publiccloud_pint_image(settings)
    assert settings["PUBLIC_CLOUD_IMAGE_ID"] == "111"
    assert "PUBLIC_CLOUD_PINT_QUERY" not in settings
    assert settings["PUBLIC_CLOUD_REGION"] == "south"
    assert "PUBLIC_CLOUD_PINT_NAME" not in settings
    assert "PUBLIC_CLOUD_PINT_REGION" not in settings
    assert "PUBLIC_CLOUD_PINT_FIELD" not in settings

    monkeypatch.setattr(
        openqabot.pc_helper, "get_recent_pint_image", lambda *args, **kwargs: None
    )
    settings = {
        "PUBLIC_CLOUD_PINT_QUERY": "test",
        "PUBLIC_CLOUD_PINT_NAME": "test",
        "PUBLIC_CLOUD_PINT_FIELD": "image_id",
        "PUBLIC_CLOUD_PINT_REGION": "south",
    }
    apply_publiccloud_pint_image(settings)
    assert settings["PUBLIC_CLOUD_IMAGE_ID"] is None
    assert "PUBLIC_CLOUD_PINT_QUERY" not in settings
    assert settings["PUBLIC_CLOUD_REGION"] == "south"
    assert "PUBLIC_CLOUD_PINT_NAME" not in settings
    assert "PUBLIC_CLOUD_PINT_REGION" not in settings
    assert "PUBLIC_CLOUD_PINT_FIELD" not in settings


def test_apply_sles4sap_pint_image_invalid_csp():
    """
    Test what happens providing an invalid CSP name:
    Guybrush is still only a pirate and not one of the 3 valid CSP names
    supported by the tested function.
    """
    res = apply_sles4sap_pint_image(
        cloud_provider="Guybrush", pint_base_url=None, name_filter=None
    )
    assert res == {}


def test_apply_sles4sap_pint_image_azure_csp():
    """
    AZURE is not supported for the moment as CSP catalog names
    support "AAA:BBB:latest" format.
    This makes calling PINT useless.
    """
    res = apply_sles4sap_pint_image(
        cloud_provider="AZURE", pint_base_url=None, name_filter=None
    )
    assert res == {}


def test_apply_sles4sap_pint_image_invalid_url():
    """
    pint_query has to be a valid url, otherwise the call silently return nothing
    """
    res = apply_sles4sap_pint_image(
        cloud_provider="AZURE", pint_base_url="DinkyIsland", name_filter=None
    )
    assert res == {}


@mock.patch("openqabot.pc_helper.pint_query")
def test_apply_sles4sap_pint_image_none_match_pint(pch):
    """
    Test PINT returning an empty image list
    """
    # this one simulate a PINT query that return nothing
    pch.side_effect = lambda *args, **kwargs: {"images": []}

    res = apply_sles4sap_pint_image(
        cloud_provider="GCE",
        pint_base_url="http://DinkyIsland",
        name_filter="StanStanman",
    )
    assert res == {}


@mock.patch("openqabot.pc_helper.pint_query")
def test_apply_sles4sap_pint_query_exception(pch):
    """
    When the JSON structure returned by PINT
    does not contain fields that the script expect to be present
    the function silently return an empty {}
    """
    pch.side_effect = Exception("PINT is on MonkeyIsland")
    res = apply_sles4sap_pint_image(
        cloud_provider="GCE",
        pint_base_url="http://DinkyIsland",
        name_filter="StanStanman",
    )
    assert res == {}


@mock.patch("openqabot.pc_helper.pint_query")
def test_apply_sles4sap_pint_image_unexpected_format(pch):
    """
    When the JSON structure returned by PINT
    does not contain fields that the script expect to be present
    the function silently return an empty {}
    """
    pch.side_effect = lambda *args, **kwargs: {"images": [{"Elaine": "Marley"}]}
    res = apply_sles4sap_pint_image(
        cloud_provider="GCE",
        pint_base_url="http://DinkyIsland",
        name_filter="StanStanman",
    )
    assert res == {}


@mock.patch("openqabot.pc_helper.pint_query")
def test_apply_sles4sap_pint_image_none_match_name(pch):
    """
    What is happening when the JSON structure returned
    by PINT does not have the name matching with requested filter?
    """
    pch.side_effect = lambda *args, **kwargs: {
        "images": [{"name": "ElaineMarley", "urn": "TriIslandArea"}]
    }
    res = apply_sles4sap_pint_image(
        cloud_provider="GCE",
        pint_base_url="http://DinkyIsland",
        name_filter="StanStanman",
    )
    assert res == {}


@mock.patch("openqabot.pc_helper.pint_query")
def test_apply_sles4sap_pint_image_gce_url_inactive(pch):
    """
    Check how the PINT url is internally composed.
    Implicitly also test that the code looks for in
    inactive images.
    """

    # Simulate pint_query and return different values
    # in case active or inactive images are requested
    # Intentionally only the inactive image will match
    # the name_filter
    def im_pint(*args, **kwargs):
        if "/active.json" in str(*args):
            return {
                "images": [
                    {
                        "name": "ElaineMarley",
                        "project": "TriIslandArea",
                        "publishedon": "1",
                        "state": "active",
                    }
                ]
            }
        return {
            "images": [
                {
                    "name": "StanStanman",
                    "project": "PlunderIsland",
                    "publishedon": "1",
                    "state": "inactive",
                }
            ]
        }

    pch.side_effect = im_pint
    res = apply_sles4sap_pint_image(
        cloud_provider="GCE",
        pint_base_url="http://DinkyIsland",
        name_filter="StanStanman",
    )
    pch.assert_any_call("http://DinkyIsland/google/images/active.json")
    pch.assert_any_call("http://DinkyIsland/google/images/inactive.json")
    assert res["PUBLIC_CLOUD_IMAGE_NAME"] == "PlunderIsland/StanStanman"
    assert res["PUBLIC_CLOUD_IMAGE_STATE"] == "inactive"


@mock.patch("openqabot.pc_helper.pint_query")
def test_apply_sles4sap_pint_image_gce_match_in_the_middle(pch):
    """
    Pint return a valid list of images, made of only one image
    matching the name_filter, but the regexp has to be more articulated
    to match in the middle.
    Test that name_filter argument is supporting various regexp
    """
    pch.side_effect = lambda *args, **kwargs: {
        "images": [
            {
                "name": "ElaineMarley",
                "project": "TriIslandArea",
                "publishedon": "1",
                "state": "active",
            }
        ]
    }
    res = apply_sles4sap_pint_image(
        cloud_provider="GCE",
        pint_base_url="http://DinkyIsland",
        name_filter=".*ineMa.*",
    )
    assert res["PUBLIC_CLOUD_IMAGE_NAME"] == "TriIslandArea/ElaineMarley"


@mock.patch("openqabot.pc_helper.pint_query")
def test_apply_sles4sap_pint_image_gce_newer(pch):
    """
    2 over 3 images from PINT match the name_filter.
    The function has to return the newer on using publishedon
    """
    pch.side_effect = lambda *args, **kwargs: {
        "images": [
            {
                "name": "ElaineMarleyJounger",
                "project": "TriIslandAreaOld",
                "publishedon": "1",
                "state": "active",
            },
            {
                "name": "ElaineMarleyOlder",
                "project": "TriIslandAreaNow",
                "publishedon": "2",
                "state": "active",
            },
            {
                "name": "VoodoLady",
                "project": "Cave",
                "publishedon": "3",
                "state": "active",
            },
        ]
    }
    res = apply_sles4sap_pint_image(
        cloud_provider="GCE",
        pint_base_url="http://DinkyIsland",
        name_filter="ElaineMarley.*",
    )
    assert res["PUBLIC_CLOUD_IMAGE_NAME"] == "TriIslandAreaNow/ElaineMarleyOlder"


@mock.patch("openqabot.pc_helper.pint_query")
def test_apply_sles4sap_pint_image_gce(pch):
    """
    Pint return a valid list of images, made of only one image
    matching the name_filter
    """
    pch.side_effect = lambda *args, **kwargs: {
        "images": [
            {
                "name": "ElaineMarley",
                "project": "TriIslandArea",
                "publishedon": "1",
                "state": "active",
            }
        ]
    }
    res = apply_sles4sap_pint_image(
        cloud_provider="GCE", pint_base_url="http://DinkyIsland", name_filter="Elaine"
    )
    assert res["PUBLIC_CLOUD_IMAGE_NAME"] == "TriIslandArea/ElaineMarley"


@mock.patch("openqabot.pc_helper.pint_query")
def test_apply_sles4sap_pint_image_gce_url(pch):
    """
    Check how the PINT url is internally composed.
    Implicitly also test that the code at first look for in
    active images.
    """
    pch.side_effect = lambda *args, **kwargs: {
        "images": [
            {
                "name": "ElaineMarley",
                "project": "TriIslandArea",
                "publishedon": "1",
                "state": "active",
            }
        ]
    }
    res = apply_sles4sap_pint_image(
        cloud_provider="GCE", pint_base_url="http://DinkyIsland", name_filter="Elaine"
    )
    pch.assert_called_with("http://DinkyIsland/google/images/active.json")


@mock.patch("openqabot.pc_helper.pint_query")
def test_apply_sles4sap_pint_image_ec2(pch):
    """
    Simulate PINT only to have one active image in one region.
    Request images using matching name and region
    """
    pch.side_effect = lambda *args, **kwargs: {
        "images": [
            {
                "name": "ElaineMarley",
                "id": "RootBeer",
                "publishedon": "1",
                "state": "active",
                "region": "TriIslandArea",
            }
        ]
    }
    res = apply_sles4sap_pint_image(
        cloud_provider="EC2",
        pint_base_url="http://DinkyIsland",
        name_filter="Elaine",
        region_list=["TriIslandArea"],
    )
    assert res["PUBLIC_CLOUD_IMAGE_NAME"] == "ElaineMarley"


@mock.patch("openqabot.pc_helper.pint_query")
def test_apply_sles4sap_pint_image_ec2_url(pch):
    """
    Test equivalent to test_apply_sles4sap_pint_image_gcp_url but for Amazon
    """
    pch.side_effect = lambda *args, **kwargs: {
        "images": [
            {
                "name": "ElaineMarley",
                "id": "RootBeer",
                "publishedon": "1",
                "state": "active",
                "region": "TriIslandArea",
            }
        ]
    }
    res = apply_sles4sap_pint_image(
        cloud_provider="EC2",
        pint_base_url="http://DinkyIsland",
        name_filter="Elaine",
        region_list=["TriIslandArea"],
    )
    pch.assert_called_with("http://DinkyIsland/amazon/images/active.json")


@mock.patch("openqabot.pc_helper.pint_query")
def test_apply_sles4sap_pint_image_ec2_multiple_regions(pch):
    """
    Simulate PINT to have same image in two regions.
    In AWS it is typical to have same image available in multiple regions: all of the image
    has the same name but different AMI (recorded in PINT under 'id' key)
    Request images using matching name and region list
    """
    pch.side_effect = lambda *args, **kwargs: {
        "images": [
            {
                "name": "ElaineMarley",
                "id": "RootBeer",
                "publishedon": "1",
                "state": "active",
                "region": "MêléeIsland",
            },
            {
                "name": "ElaineMarley",
                "id": "BananaPicker",
                "publishedon": "1",
                "state": "active",
                "region": "HookIsle",
            },
        ]
    }
    res = apply_sles4sap_pint_image(
        cloud_provider="EC2",
        pint_base_url="http://DinkyIsland",
        name_filter="Elaine",
        region_list=["MêléeIsland", "HookIsle"],
    )
    assert res["PUBLIC_CLOUD_IMAGE_NAME"] == "ElaineMarley"
    assert res["PUBLIC_CLOUD_IMAGE_NAME_REGIONS"] == "MêléeIsland;HookIsle"
    assert res["PUBLIC_CLOUD_IMAGE_NAME_ID"] == "RootBeer;BananaPicker"


@mock.patch("openqabot.pc_helper.pint_query")
def test_apply_sles4sap_pint_image_ec2_multiple_regions_filtered(pch):
    """
    Simulate PINT to have same image in two regions AAA and BBB.
    Request images using matching name but region list like AAA and CCC.
    Expected result is that only AAA image is returned
    """
    pch.side_effect = lambda *args, **kwargs: {
        "images": [
            {
                "name": "ElaineMarley",
                "id": "RootBeer",
                "publishedon": "1",
                "state": "active",
                "region": "MêléeIsland",
            },
            {
                "name": "ElaineMarley",
                "id": "BananaPicker",
                "publishedon": "1",
                "state": "active",
                "region": "HookIsle",
            },
        ]
    }
    res = apply_sles4sap_pint_image(
        cloud_provider="EC2",
        pint_base_url="http://DinkyIsland",
        name_filter="Elaine",
        region_list=["MêléeIsland", "MonkeyIsland"],
    )
    assert res["PUBLIC_CLOUD_IMAGE_NAME"] == "ElaineMarley"
    assert res["PUBLIC_CLOUD_IMAGE_NAME_REGIONS"] == "MêléeIsland"
    assert res["PUBLIC_CLOUD_IMAGE_NAME_ID"] == "RootBeer"


def test_get_recent_pint_image():
    images = []
    ret = get_recent_pint_image(images, "test")
    assert ret is None

    img1 = {
        "name": "test",
        "state": "active",
        "publishedon": "20231212",
        "region": "south",
    }
    images.append(img1)
    ret = get_recent_pint_image(images, "test")
    assert ret == img1

    ret = get_recent_pint_image(images, "AAAAA")
    assert ret is None

    ret = get_recent_pint_image(images, "test", "north")
    assert ret is None

    ret = get_recent_pint_image(images, "test", "south")
    assert ret == img1

    ret = get_recent_pint_image(images, "test", "south", "inactive")
    assert ret is None

    img2 = {
        "name": "test",
        "state": "inactive",
        "publishedon": "20231212",
        "region": "south",
    }
    images.append(img2)
    ret = get_recent_pint_image(images, "test", "south", "inactive")
    assert ret == img2

    img3 = {
        "name": "test",
        "state": "inactive",
        "publishedon": "30231212",
        "region": "south",
    }
    images.append(img3)
    ret = get_recent_pint_image(images, "test", "south", "inactive")
    assert ret == img3


@responses.activate
def test_get_latest_tools_image():
    responses.add(
        responses.GET,
        re.compile(r"http://url/.*"),
        json={"build_results": []},
    )
    ret = get_latest_tools_image("http://url/results")
    assert ret is None

    responses.add(
        responses.GET,
        re.compile(r"http://url/.*"),
        json={
            "build_results": [
                {"failed": 10, "build": "AAAAA"},
                {"failed": 0, "build": "test"},
            ]
        },
    )
    ret = get_latest_tools_image("http://url/results")
    assert ret == "publiccloud_tools_test.qcow2"
