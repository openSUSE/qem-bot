# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import re
from functools import lru_cache
from logging import getLogger
from typing import Any, Dict, List, Optional

from .utils import retry5 as retried_requests

log = getLogger("openqabot.pc_helper")


def get_latest_tools_image(query: str) -> Optional[str]:
    """Get latest tools image.

    'publiccloud_tools_<BUILD NUM>.qcow2' is a generic name for an image used by Public Cloud tests to run
    in openQA. A query is supposed to look like this "https://openqa.suse.de/group_overview/276.json" to get
    a value for <BUILD NUM>
    """
    # Get the first not-failing item
    build_results = retried_requests.get(query).json()["build_results"]
    for build in build_results:
        if build["failed"] == 0:
            return "publiccloud_tools_{}.qcow2".format(build["build"])
    return None


def apply_pc_tools_image(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the PC tools image in settings.

    Use PUBLIC_CLOUD_TOOLS_IMAGE_QUERY to get latest tools image and set it into
    PUBLIC_CLOUD_TOOLS_IMAGE_BASE
    """
    try:
        if "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY" in settings:
            settings["PUBLIC_CLOUD_TOOLS_IMAGE_BASE"] = get_latest_tools_image(
                settings["PUBLIC_CLOUD_TOOLS_IMAGE_QUERY"],
            )
    except BaseException as e:  # noqa: BLE001 true-positive: Consider to use fine-grained exceptions
        log_error = "PUBLIC_CLOUD_TOOLS_IMAGE_BASE handling failed"
        if "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY" in settings:
            log_error += f" PUBLIC_CLOUD_TOOLS_IMAGE_QUERY={settings['PUBLIC_CLOUD_TOOLS_IMAGE_QUERY']}"
        log.warning("%s : %s", log_error, e)
    finally:
        settings.pop("PUBLIC_CLOUD_TOOLS_IMAGE_QUERY", None)
    return settings


@lru_cache(maxsize=None)
def pint_query(query: str) -> Dict[str, Any]:
    """Perform a pint query.

    Successive queries are cached
    """
    return retried_requests.get(query).json()


def apply_publiccloud_pint_image(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Apply PUBLIC_CLOUD_IMAGE_LOCATION based on the given PUBLIC_CLOUD_IMAGE_REGEX."""
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
    images: List[Dict[str, Any]],
    name_regex: str,
    region: Optional[str] = None,
    state: str = "active",
) -> Optional[Dict[str, Any]]:
    """Get most recent PINT image.

    From the given set of images (received json from pint),
    get the latest one that matches the given criteria:
     - name given as regular expression,
     - region given as string,
     - state given the state of the image

    Get the latest one based on 'publishedon'
    """
    name = re.compile(name_regex)
    if region == "":
        region = None
    recentimage = None

    def is_newer(date1: str, date2: str) -> bool:
        # Checks if date1 is newer than date2. Expected date format: YYYYMMDD
        # Because for the format, we can do a simple int comparison
        return int(date1) > int(date2)

    for image in images:
        # Apply selection criteria: state and region criteria
        # can be omitted by setting the corresponding variable to None
        # This is required, because certain public cloud providers
        # do not make a distinction on e.g. the region
        # and thus this check is not needed there
        if name.match(image["name"]) is None:
            continue
        if (state is not None) and (image["state"] != state):
            continue
        if (region is not None) and (region != image["region"]):
            continue
        # Get latest one based on 'publishedon'
        if recentimage is None or is_newer(image["publishedon"], recentimage["publishedon"]):
            recentimage = image
    return recentimage
