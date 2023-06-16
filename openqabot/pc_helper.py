# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from functools import lru_cache
import logging
import re

import bs4

from .utils import retry5 as requests

log = logging.getLogger("bot.openqabot.pc_helper")


def fetch_matching_link(url, regex):
    """
    Apply odering by modification date (ascending) and return the first link that matches the given regex
    """
    try:
        # Note: ?C=M;O=A - C - compare , M - modify time , O - order , A - asc
        # So, the first link matching the regex is the most recent one
        req = requests.get(url + "/?C=M;O=A")
        text = req.text
    except BaseException as err:
        log.error("error fetching '%s': %s" % (url, err))
        return None
    getpage_soup = bs4.BeautifulSoup(text, "html.parser")
    # Returns lazy iterator, so
    links = getpage_soup.findAll("a", href=regex)
    if links:
        return f"{url}/{links[0].get('href')}"
    raise ValueError("No matching links found")


def get_latest_pc_image(image):
    """
    Gets the latest image from the given URL/regex image is of the format 'URL/regex'
    """
    basepath, _, regex = image.rpartition("/")
    return fetch_matching_link(basepath, re.compile(regex))


def get_latest_tools_image(query):
    """
    'publiccloud_tools_<BUILD NUM>.qcow2' is a generic name for an image used by Public Cloud tests to run
    in openQA. A query is supposed to look like this "https://openqa.suse.de/group_overview/276.json" to get
    a value for <BUILD NUM>
    """

    ## Get the first not-failing item
    build_results = requests.get(query).json()["build_results"]
    for build in build_results:
        if build["failed"] == 0:
            return "publiccloud_tools_{}.qcow2".format(build["build"])
    return None


def apply_publiccloud_regex(settings):
    """
    Applies PUBLIC_CLOUD_IMAGE_LOCATION based on the given PUBLIC_CLOUD_IMAGE_REGEX
    """
    try:
        settings["PUBLIC_CLOUD_IMAGE_LOCATION"] = get_latest_pc_image(
            settings["PUBLIC_CLOUD_IMAGE_REGEX"]
        )
        return settings
    except BaseException as e:
        log.warning(f"PUBLIC_CLOUD_IMAGE_REGEX handling failed: {e}")
        settings["PUBLIC_CLOUD_IMAGE_LOCATION"] = None
        return settings


def apply_pc_tools_image(settings):
    """
    Use PUBLIC_CLOUD_TOOLS_IMAGE_QUERY to get latest tools image and set it into
    PUBLIC_CLOUD_TOOLS_IMAGE_BASE
    """
    try:
        if "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY" in settings:
            settings["PUBLIC_CLOUD_TOOLS_IMAGE_BASE"] = get_latest_tools_image(
                settings["PUBLIC_CLOUD_TOOLS_IMAGE_QUERY"]
            )
            del settings["PUBLIC_CLOUD_TOOLS_IMAGE_QUERY"]
        return settings
    except BaseException as e:
        log.warning(f"PUBLIC_CLOUD_TOOLS_IMAGE_BASE handling failed: {e}")
        return settings


@lru_cache(maxsize=None)
def pint_query(query):
    """
    Perform a pint query. Sucessive queries are cached
    """
    return requests.get(query).json()


def apply_publiccloud_pint_image(settings):
    """
    Applies PUBLIC_CLOUD_IMAGE_LOCATION based on the given PUBLIC_CLOUD_IMAGE_REGEX
    """
    try:
        images = pint_query(settings["PUBLIC_CLOUD_PINT_QUERY"])["images"]
        region = (
            settings["PUBLIC_CLOUD_PINT_REGION"]
            if "PUBLIC_CLOUD_PINT_REGION" in settings
            else None
        )
        # We need to include active and inactive images. Active images have precedence
        # inactive images are maintained PC images which only receive security updates.
        # See https://www.suse.com/c/suse-public-cloud-image-life-cycle/
        image = None
        for state in ["active", "inactive", "deprecated"]:
            image = get_recent_pint_image(
                images, settings["PUBLIC_CLOUD_PINT_NAME"], region, state=state
            )
            if image is not None:
                break
        if image is None:
            raise ValueError("Cannot find matching image in pint")
        settings["PUBLIC_CLOUD_IMAGE_ID"] = image[settings["PUBLIC_CLOUD_PINT_FIELD"]]
        settings["PUBLIC_CLOUD_IMAGE_NAME"] = image["name"]
        settings["PUBLIC_CLOUD_IMAGE_STATE"] = image["state"]
        # Remove pint query settings. They are not required in the scheduled job
        if "PUBLIC_CLOUD_PINT_QUERY" in settings:
            del settings["PUBLIC_CLOUD_PINT_QUERY"]
        if "PUBLIC_CLOUD_PINT_NAME" in settings:
            del settings["PUBLIC_CLOUD_PINT_NAME"]
        if "PUBLIC_CLOUD_PINT_REGION" in settings:
            # If we define a region for the pint query, propagate this value
            settings["PUBLIC_CLOUD_REGION"] = settings["PUBLIC_CLOUD_PINT_REGION"]
            del settings["PUBLIC_CLOUD_PINT_REGION"]
        if "PUBLIC_CLOUD_PINT_FIELD" in settings:
            del settings["PUBLIC_CLOUD_PINT_FIELD"]
        return settings
    except BaseException as e:
        log.warning(
            f"PUBLIC_CLOUD_PINT_QUERY handling failed for {settings['PUBLIC_CLOUD_PINT_NAME']}: {e}"
        )
        settings["PUBLIC_CLOUD_IMAGE_ID"] = None
        return settings


def get_recent_pint_image(images, name_regex, region=None, state="active"):
    """
    From the given set of images (received json from pint), get the latest one that matches the given criteria (name given as regular expression, region given as string, and state given the state of the image)
    Get the latest one based on 'publishedon'
    """

    def is_newer(date1, date2):
        # Checks if date1 is newer than date2. Expected date format: YYYYMMDD
        # Because for the format, we can do a simple int comparison
        return int(date1) > int(date2)

    name = re.compile(name_regex)
    if region == "":
        region = None
    recentimage = None
    for image in images:
        # Apply selection criteria. state and region criteria can be omitted by setting the corresponding variable to None
        # This is required, because certain public cloud providers do not make a distinction on e.g. the region and thus this check is not needed there
        if name.match(image["name"]) is None:
            continue
        if (state is not None) and (image["state"] != state):
            continue
        if (region is not None) and (region != image["region"]):
            continue
        # Get latest one based on 'publishedon'
        if recentimage is None or is_newer(
            image["publishedon"], recentimage["publishedon"]
        ):
            recentimage = image
    return recentimage
