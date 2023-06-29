#!/usr/bin/env python3
# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from pathlib import Path
from openqabot.utils import create_logger
from openqabot.loader.config import load_metadata
from openqabot.types.incident import Incident


def main():
    """
    This code is used only for testing purpose.
    Allowing to prove that Public Cloud related logic is actually working without executing
    a lot of code which is unrelated to pc_helper
    """
    log = create_logger("pc_helper_online")
    products = load_metadata(Path('/home/asmorodskyi/source/metadata/bot-ng/'),False,True, {})
    incidents = []
    incidents.append(Incident({'approved': False, 'channels': ['SUSE:Updates:OpenStack-Cloud:9:x86_64'], 'emu': False, 'inReview': False, 'inReviewQAM': False, 'isActive': True, 'number': 17958, 'packages': ['ndctl'], 'project': 'SUSE:Maintenance:17958', 'rr_number': None}))
    for product in products:
        log.error(f" Calling for {product}")
        product(incidents,{"token": "DDDDD"}, "DDDDD", True)



if __name__ == '__main__':
    main()
