import bs4
import re
import requests
import logging
from copy import deepcopy

logger = logging.getLogger("bot.openqabot.pc_helper")


def request_get(url):
    """
    Do a HTTP get request. Return the request object for further processing
    Raises a ValueError when the request fails
    """
    req = requests.get(url)
    if req.status_code != 200:
        raise ValueError("http status code %d" % (page.status_code))
    return req


def fetch_matching_link(url, regex):
    """
    Apply odering by modification date (ascending) and return the first link that matches the given regex
    """
    try:
        # Note: ?C=M;O=A - C - compare , M - modify time , O - order , A - asc
        # So, the first link matching the regex is the most recent one
        req = requests.get(url + "/?C=M;O=A")
        text = req.text
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        ValueError,
    ) as err:
        logger.error("error fetching '%s': %s" % (url, err))
        return None
    getpage_soup = bs4.BeautifulSoup(text, "html.parser")
    # Returns lazy iterator, so
    links = getpage_soup.findAll("a", href=regex)
    if links:
        return f"{url}/{links[0].get('href')}"
    raise ValueError("No matching links found")


# Gets the latest image from the given URL/regex
# image is of the format 'URL/regex'
def get_latest_pc_image(image):
    basepath, _, regex = image.rpartition("/")
    return fetch_matching_link(basepath, re.compile(regex))


# Applies PUBLIC_CLOUD_IMAGE_LOCATION based on the given PUBLIC_CLOUD_IMAGE_REGEX
def apply_publiccloud_regex(settings):
    try:
        settings["PUBLIC_CLOUD_IMAGE_LOCATION"] = get_latest_pc_image(
            settings["PUBLIC_CLOUD_IMAGE_REGEX"]
        )
        return settings
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        ValueError,
        re.error,
    ) as e:
        logger.warning(f"PUBLIC_CLOUD_IMAGE_REGEX handling failed:  {e}")
        settings["PUBLIC_CLOUD_IMAGE_LOCATION"] = None
        return settings


# Applies PUBLIC_CLOUD_IMAGE_LOCATION based on the given PUBLIC_CLOUD_IMAGE_REGEX
def apply_publiccloud_pint_image(settings):
    try:
        # TODO: Prevent multiple requests by caching
        images = request_get(settings["PUBLICCLOUD_PINT_QUERY"]).json()["images"]
        region = (
            settings["PUBLICCLOUD_PINT_REGION"]
            if "PUBLICCLOUD_PINT_REGION" in settings
            else None
        )
        image = get_recent_pint_image(images, settings["PUBLICCLOUD_PINT_NAME"], region)
        if image is None:
            raise ValueError("Cannot find matching image")
        settings["PUBLIC_CLOUD_IMAGE_ID"] = image[settings["PUBLICCLOUD_PINT_FIELD"]]
        # Remove internal settings
        if "PUBLICCLOUD_PINT_QUERY" in settings:
            del settings["PUBLICCLOUD_PINT_QUERY"]
        if "PUBLICCLOUD_PINT_NAME" in settings:
            del settings["PUBLICCLOUD_PINT_NAME"]
        if "PUBLICCLOUD_PINT_REGION" in settings:
            del settings["PUBLICCLOUD_PINT_REGION"]
        if "PUBLICCLOUD_PINT_FIELD" in settings:
            del settings["PUBLICCLOUD_PINT_FIELD"]
        return settings
    except (
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        ValueError,
        re.error,
    ) as e:
        logger.warning(f"PUBLICCLOUD_PINT_QUERY handling failed:  {e}")
        settings["PUBLIC_CLOUD_IMAGE_ID"] = None
        return settings


def get_recent_pint_image(images, name_regex, region=None, states=["active"]):
    """
    From the given set of images (received json from pint), get the latest one that matches the given criteria (name given as regular expression, region given as string, and states given as string list of accepted states)
    Get the latest one based on 'publishedon'
    """

    def is_newer(date1, date2):
        # Checks if date1 is newer than date2. Expected date format: YYYYMMDD
        # Because for the format, we can do a simple int comparison
        return int(date1) < int(date2)

    name = re.compile(name_regex)
    if region == "":
        region = None
    recentimage = None
    for image in images:
        # Apply selection criteria
        if not image["state"] in states:
            continue
        if (not region is None) and not (region in image["region"]):
            continue
        if name.match(image["name"]) is None:
            continue
        # Get latest one based on 'publishedon'
        if recentimage is None or is_newer(
            image["publishedon"], recentimage["publishedon"]
        ):
            recentimage = image
    return recentimage
