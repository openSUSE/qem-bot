#!/usr/bin/env python3
# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import ArgumentParser
from pathlib import Path
from ruamel.yaml import YAML  # type: ignore
from openqabot.utils import create_logger
from openqabot.pc_helper import apply_pc_tools_image, apply_publiccloud_pint_image


def main():
    """
    This code is used only for testing purpose.
    Allowing to prove that Public Cloud related logic is actually working without executing
    a lot of code which is unrelated to pc_helper.
    As input it getting same folder as bot-ng but processing only two variables which are related to Public Cloud
    """
    log = create_logger("pc_helper_online")
    parser = ArgumentParser(
                    prog='pc_helper_online',
                    description='Dummy code to test functionality related to pc_helper code')
    parser.add_argument(
        "-c",
        "--configs",
        type=Path,
        default=Path("/etc/openqabot"),
        help="Directory with openqabot configuration metadata",
    )
    args = parser.parse_args()
    loader = YAML(typ="safe")
    log.info(f"Parsing configuration files from {args.configs}")
    for p in Path(args.configs).glob("*.yml"):
        try:
            data = loader.load(p)
            log.info(f"Processing {p}")
            if "settings" in data:
                settings = data["settings"]
                if "PUBLIC_CLOUD_TOOLS_IMAGE_QUERY" in settings:
                    apply_pc_tools_image(settings)
                    if not settings.get("PUBLIC_CLOUD_TOOLS_IMAGE_BASE", False):
                        log.error(f"Failed to get PUBLIC_CLOUD_TOOLS_IMAGE_BASE from {data}")
                if "PUBLIC_CLOUD_PINT_QUERY" in settings:
                    apply_publiccloud_pint_image(settings)
                    if not settings.get("PUBLIC_CLOUD_IMAGE_ID", False):
                        log.error(f"Failed to get PUBLIC_CLOUD_IMAGE_ID from {data}")
        except Exception as e:
            log.exception(e)
            continue



if __name__ == '__main__':
    main()
