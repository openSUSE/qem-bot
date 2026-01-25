# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from functools import cache
from logging import getLogger
from operator import itemgetter
from typing import Any

from .utils import retry5 as retried_requests

log = getLogger("openqabot.pc_helper")


def get_latest_tools_image(query: str) -> str | None:
    """Get latest tools image.

    'publiccloud_tools_<BUILD NUM>.qcow2' is a generic name for an image used by Public Cloud tests to run
    in openQA. A query is supposed to look like this "https://openqa.suse.de/group_overview/276.json" to get
    a value for <BUILD NUM>
    """
    # Get the first not-failing item
    build_results = retried_requests.get(query).json()["build_results"]
    return next(
        ("publiccloud_tools_{}.qcow2".format(build["build"]) for build in build_results if build["failed"] == 0),
        None,
    )


def apply_pc_tools_image(settings: dict[str, Any]) -> dict[str, Any]:
    """Apply the PC tools image in settings.

    Use PUBLIC_CLOUD_TOOLS_IMAGE_QUERY to get latest tools image and set it into
    PUBLIC_CLOUD_TOOLS_IMAGE_BASE
    """
    query_key = "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY"
    try:
        if query_key in settings:
            settings["PUBLIC_CLOUD_TOOLS_IMAGE_BASE"] = get_latest_tools_image(settings[query_key])
    except BaseException as e:  # noqa: BLE001 true-positive: Consider to use fine-grained exceptions
        log.warning("Public Cloud image base handling failed: Query %s: %s", settings[query_key], e)
    finally:
        settings.pop(query_key, None)
    return settings


@cache
def pint_query(query: str) -> dict[str, Any]:
    """Perform a pint query.

    Successive queries are cached
    """
    return retried_requests.get(query).json()


def apply_publiccloud_pint_image(settings: dict[str, Any]) -> dict[str, Any]:
    """Apply PUBLIC_CLOUD_IMAGE_LOCATION based on the given PUBLIC_CLOUD_IMAGE_REGEX."""
    if "PUBLIC_CLOUD_IMAGE_ID" in settings:
        return settings
    try:
        region = settings.get("PUBLIC_CLOUD_PINT_REGION")
        # We need to include active and inactive images. Active images have precedence
        # inactive images are maintained PC images which only receive security updates.
        # See https://www.suse.com/c/suse-public-cloud-image-life-cycle/
        image = None
        for state in ["active", "inactive", "deprecated"]:
            images = pint_query(f"{settings['PUBLIC_CLOUD_PINT_QUERY']}{state}.json")["images"]
            image = get_recent_pint_image(images, settings["PUBLIC_CLOUD_PINT_NAME"], region, state=state)
            if image is not None:
                break
        if image is None:
            msg = "Cannot find matching image in pint"
            raise ValueError(msg)  # noqa: TRY301
        settings["PUBLIC_CLOUD_IMAGE_ID"] = image[settings["PUBLIC_CLOUD_PINT_FIELD"]]
        settings["PUBLIC_CLOUD_IMAGE_NAME"] = image["name"]
        settings["PUBLIC_CLOUD_IMAGE_STATE"] = image["state"]
    except BaseException as e:  # noqa: BLE001 true-positive: Consider to use fine-grained exceptions
        log_error = "PUBLIC_CLOUD_PINT_QUERY handling failed"
        if "PUBLIC_CLOUD_PINT_NAME" in settings:
            log_error += f" for {settings['PUBLIC_CLOUD_PINT_NAME']}"
        log.warning("{%s: %s", log_error, e)
        settings["PUBLIC_CLOUD_IMAGE_ID"] = None
    finally:
        settings.pop("PUBLIC_CLOUD_PINT_QUERY", None)
        settings.pop("PUBLIC_CLOUD_PINT_NAME", None)
        if "PUBLIC_CLOUD_PINT_REGION" in settings:
            # If we define a region for the pint query, propagate this value
            settings["PUBLIC_CLOUD_REGION"] = settings["PUBLIC_CLOUD_PINT_REGION"]
            del settings["PUBLIC_CLOUD_PINT_REGION"]
        settings.pop("PUBLIC_CLOUD_PINT_FIELD", None)
    return settings


def get_recent_pint_image(
    images: list[dict[str, Any]],
    name_regex: str,
    region: str | None = None,
    state: str = "active",
) -> dict[str, Any] | None:
    """Get most recent PINT image.

    From the given set of images (received json from pint),
    get the latest one that matches the given criteria:
     - name given as regular expression,
     - region given as string,
     - state given the state of the image

    Get the latest one based on 'publishedon'
    """
    name = re.compile(name_regex)

    # Apply selection criteria: state and region criteria can be omitted by setting the corresponding variable to None
    # This is required, because certain public cloud providers do not make a distinction on e.g. the region and thus
    # this check is not needed there
    filtered_images = [
        image
        for image in images
        if name.match(image["name"]) is not None
        and (state is None or image["state"] == state)
        and (region is None or not region or region == image["region"])
    ]
    if not filtered_images:
        return None
    return max(filtered_images, key=itemgetter("publishedon"))
