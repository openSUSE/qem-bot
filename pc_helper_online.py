#!/usr/bin/env python3
# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from openqabot.pc_helper import apply_pc_tools_image, apply_publiccloud_pint_image
from openqabot.utils import create_logger


def main():
    """
    This code is used only for testing purpose.
    Allowing to prove that Public Cloud related logic is actually working without executing
    a lot of code which is unrelated to pc_helper
    """
    log = create_logger("pc_helper_online")
    settings = {
        "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY": "https://openqa.suse.de/group_overview/276.json"
    }
    log.info("Calling apply_pc_tools_image with :\n%s", settings)
    apply_pc_tools_image(settings)
    log.info("Setting after the call to apply_pc_tools_image:\n%s", settings)

    settings = {
        "PUBLIC_CLOUD_PINT_QUERY": "https://susepubliccloudinfo.suse.com/v1/amazon/images/",
        "PUBLIC_CLOUD_PINT_NAME": "suse-sles-12-sp5-v[0-9]{8}-hvm-ssd-x86_64",
        "PUBLIC_CLOUD_PINT_REGION": "us-east-1",
        "PUBLIC_CLOUD_PINT_FIELD": "id",
    }
    log.info("Calling apply_publiccloud_pint_image with :\n%s", settings)
    apply_publiccloud_pint_image(settings)
    log.info("Setting after the call to apply_publiccloud_pint_image:\n%s", settings)

    settings = {
        "PUBLIC_CLOUD_PINT_QUERY": "https://susepubliccloudinfo.suse.com/v1/amazon/images/",
        "PUBLIC_CLOUD_PINT_NAME": "suse-sles-15-sp2-chost-byos-v[0-9]{8}-hvm-ssd-x86_64",
        "PUBLIC_CLOUD_PINT_REGION": "us-east-1",
        "PUBLIC_CLOUD_PINT_FIELD": "id",
    }
    log.info("Calling apply_publiccloud_pint_image with :\n%s", settings)
    apply_publiccloud_pint_image(settings)
    log.info("Setting after the call to apply_publiccloud_pint_image:\n%s", settings)


if __name__ == "__main__":
    main()
