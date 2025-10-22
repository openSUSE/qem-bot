# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import re

import openqabot.pc_helper
import responses
from openqabot.pc_helper import (
    apply_pc_tools_image,
    apply_publiccloud_pint_image,
    get_latest_tools_image,
    get_recent_pint_image,
)


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
    monkeypatch.setattr(openqabot.pc_helper, "pint_query", lambda *args, **kwargs: {"images": []})
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

    monkeypatch.setattr(openqabot.pc_helper, "get_recent_pint_image", lambda *args, **kwargs: None)
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
