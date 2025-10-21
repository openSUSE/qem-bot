#!/usr/bin/env python3
# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

"""Helper for Public Cloud testing."""

from argparse import ArgumentParser
from pathlib import Path
from ruamel.yaml import YAML
from openqabot.pc_helper import apply_pc_tools_image, apply_publiccloud_pint_image
from openqabot.utils import create_logger, get_yml_list


def main():
    """
    Run Public Cloud helper with online access for testing purposes.

    Allowing to prove that Public Cloud related logic is actually working without executing
    a lot of code which is unrelated to pc_helper.
    As input it getting directory with openqabot configuration metadata (same folder as qem-bot )
    but processing only variables related to openqabot.pc_helper module
    """
    log = create_logger("pc_helper_online")
    parser = ArgumentParser(
        prog="pc_helper_online",
        description="Dummy code to test functionality related to pc_helper code",
    )
    parser.add_argument(
        "-c",
        "--configs",
        type=Path,
        default=Path("/etc/openqabot"),
        help="Directory with openqabot configuration metadata",
    )
    args = parser.parse_args()
    log.info("Parsing configuration files from %s", args.configs)
    loader = YAML(typ="safe")
    for p in get_yml_list(Path(args.configs)):
        try:
            data = loader.load(p)
            log.info("Processing %s", p)
            if "settings" in data:
                settings = data["settings"]
                if "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY" in settings:
                    apply_pc_tools_image(settings)
                    if "PUBLIC_CLOUD_TOOLS_IMAGE_BASE" not in settings:
                        log.error("Failed to get PUBLIC_CLOUD_TOOLS_IMAGE_BASE from %s", data)
                if "PUBLIC_CLOUD_PINT_QUERY" in settings:
                    apply_publiccloud_pint_image(settings)
                    if "PUBLIC_CLOUD_IMAGE_ID" not in settings:
                        log.error("Failed to get PUBLIC_CLOUD_IMAGE_ID from %s", data)
        except Exception as e:  # pylint: disable=broad-except
            log.exception(e)
            continue


if __name__ == "__main__":
    main()
