# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from functools import lru_cache
from logging import getLogger
import re

from .utils import retry5 as requests

log = getLogger("openqabot.pc_helper")


def get_latest_tools_image(query):
    """
    'publiccloud_tools_<BUILD NUM>.qcow2' is a generic name
    for an image used by Public Cloud tests to run in openQA.
    A query is supposed to look like this
    "https://openqa.suse.de/group_overview/276.json"
    to get a value for <BUILD NUM>
    """

    ## Get the first not-failing item
    build_results = requests.get(query).json()["build_results"]
    for build in build_results:
        if build["failed"] == 0:
            return "publiccloud_tools_{}.qcow2".format(build["build"])
    return None


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
    except BaseException as e:
        log_error = f"PUBLIC_CLOUD_TOOLS_IMAGE_BASE handling failed"
        if "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY" in settings:
            log_error += f" PUBLIC_CLOUD_TOOLS_IMAGE_QUERY={settings['PUBLIC_CLOUD_TOOLS_IMAGE_QUERY']}"
        log.warning(f"{log_error} : {e}")
    finally:
        del settings["PUBLIC_CLOUD_TOOLS_IMAGE_QUERY"]
    return settings


@lru_cache(maxsize=None)
def pint_query(query):
    """
    Perform a pint query. Successive queries are cached
    """
    return requests.get(query).json()


def apply_publiccloud_pint_image(settings):
    """
    Applies PUBLIC_CLOUD_IMAGE_LOCATION based on the given PUBLIC_CLOUD_IMAGE_REGEX
    """
    try:
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
            images = pint_query(f"{settings['PUBLIC_CLOUD_PINT_QUERY']}{state}.json")[
                "images"
            ]
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
    except BaseException as e:
        log_error = "PUBLIC_CLOUD_PINT_QUERY handling failed"
        if "PUBLIC_CLOUD_PINT_NAME" in settings:
            log_error += f' for {settings["PUBLIC_CLOUD_PINT_NAME"]}'
        log.warning(f"{log_error}: {e}")
        settings["PUBLIC_CLOUD_IMAGE_ID"] = None
    finally:
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


def get_pint_image(name_filter, field, state, query, region=None):
    """
    Calculate the most recent image in PINT:
    1. Compose PINT url using query+state,
    2. get list of images from the url,
    3. search the one with name matching the filter,
    4. return the newest one.

    :param str name_filter passed to get_recent_pint_image
    :param str field key name in dictionary returned by PINT to be used as ID in the return dictionary
    :param str state active/inactive used as name of the json file in PINT url
    :param str query url of PINT, has not to have '/' at the end
    :param str region optional filter, mostly needed by AWS
    :return two keys dictionary: NAME and ID or an empty dictionary in case of error
    """
    settings = {}
    url = f"{query}/{state}.json"
    log.debug("Pint url:%s name_filter:%s region:%s", url, name_filter, region)
    try:
        images = pint_query(url)["images"]
        image = get_recent_pint_image(images, name_filter, region=region, state=state)
        if image is None:
            raise ValueError(
                f"Cannot find matching image in PINT with name:[{name_filter}] and state:{state}"
            )
        if field not in image.keys() or "name" not in image.keys():
            raise ValueError(
                f"Cannot find expected keys '{field}' in the selected image dictionary {image}"
            )
        settings["ID"] = image[field]
        settings["NAME"] = image["name"]
    except BaseException as e:
        log.warning(f"get_pint_image handling failed: {e}")
    log.debug("Return settings:%s", settings)
    return settings


def pint_url(pint_base_url, csp_name):
    """
    :param str pint_base_url, usually https://susepubliccloudinfo.suse.com/v1
    :param str csp_name microsoft, amazon, google, ...
    :return str PINT url for the images API
    """
    url = f"{pint_base_url}/{csp_name}/images"
    log.debug("PINT url:%s", url)
    return url


def sles4sap_pint_gce(name_filter, state, pint_base_url):
    """
    Query PINT about GCE images and retrieve the latest one
    """
    job_settings = {}
    ret = get_pint_image(
        name_filter=name_filter,
        field="project",
        state=state,
        query=pint_url(pint_base_url, "google"),
    )
    if any(ret):
        job_settings["PUBLIC_CLOUD_IMAGE_NAME"] = f"{ret['ID']}/{ret['NAME']}"
        job_settings["PUBLIC_CLOUD_IMAGE_STATE"] = state
    return job_settings


def sles4sap_pint_ec2(name_filter, state, pint_base_url, region_list):
    """
    Query PINT about EC2 images and retrieve the latest one
    for each of the requested regions.
    Returned data is organized in a different way from sles4sap_pint_azure
    and sles4sap_pint_gce
    """
    job_settings = {}
    images_list = {}
    for this_region in region_list:
        ret = get_pint_image(
            name_filter=name_filter,
            field="id",
            state=state,
            query=pint_url(pint_base_url, "amazon"),
            region=this_region,
        )
        if any(ret):
            images_list[this_region] = ret
    if any(images_list):
        # All element should have same name, just get the first
        job_settings["PUBLIC_CLOUD_IMAGE_NAME"] = next(iter(images_list.items()))[1][
            "NAME"
        ]
        job_settings["PUBLIC_CLOUD_IMAGE_STATE"] = state
        job_settings["SLES4SAP_QESAP_OS_OWNER"] = "aws-marketplace"
        # Pack all pairs region/AMI in a ';' separated values string
        setting_regions = []
        setting_ami = []
        for image_region, image_settings in images_list.items():
            setting_regions.append(image_region)
            setting_ami.append(image_settings["ID"])
        job_settings["PUBLIC_CLOUD_IMAGE_NAME_REGIONS"] = ";".join(setting_regions)
        job_settings["PUBLIC_CLOUD_IMAGE_NAME_ID"] = ";".join(setting_ami)
    return job_settings


def apply_sles4sap_pint_image(
    cloud_provider, pint_base_url, name_filter, region_list=None
):
    """
    Return OS_IMAGE related settings based on the given SLES4SAP_IMAGE_REGEX
    :param str cloud_provider uppercase cps name: could be one of AZURE|GCE|EC2
    :param str pint_base_url forwarded to lower layer, usually is https://susepubliccloudinfo.suse.com/v1
    :param str name_filter forwarded to lower layer to pint_url
    :param str region_list=None only considered by EC2
    :return dict Dictionary of OS_IMAGE related settings
    """
    job_settings = {}
    for state in ["active", "inactive"]:
        if "GCE" in cloud_provider:
            job_settings = sles4sap_pint_gce(name_filter, state, pint_base_url)
        elif "EC2" in cloud_provider:
            job_settings = sles4sap_pint_ec2(
                name_filter, state, pint_base_url, region_list
            )
        if any(job_settings):
            break
    log.debug("Sles4sap job settings:%s", job_settings)
    return job_settings


def get_recent_pint_image(images, name_regex, region=None, state="active"):
    """
    From the given set of images (received json from pint),
    get the latest one that matches the given criteria:
     - name given as regular expression,
     - region given as string,
     - state given the state of the image

    Get the latest one based on 'publishedon'
    :param list images field adressed by "images" key in json returned by pint_query
    :param str name_regex has to be valid regexp, will be passed to re.compile
    :param str region if provided only considers images for this region
    :param str state only considers images with this state
    :return dict selected image
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
        if recentimage is None or is_newer(
            image["publishedon"], recentimage["publishedon"]
        ):
            recentimage = image
    return recentimage
