# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from hashlib import md5
from logging import getLogger
from typing import List, Tuple
from xml.etree import ElementTree as ET
from datetime import datetime 

import requests

from ..errors import NoRepoFoundError

logger = getLogger("bot.loader.repohash")


def get_max_revision(
    repos: List[Tuple[str, str]],
    arch: str,
    project: str,
) -> int:

    max_rev = 0

    url_base = f"http://download.suse.de/ibs/{project.replace(':',':/')}"

    for repo in repos:
        # workaround for manager server 4.1
        if (
            arch == "aarch64"
            and repo[0] == "SLE-Module-SUSE-Manager-Server"
            and repo[1] == "4.1"
        ):
            continue

        # don't use openSUSE-SLE
        if repo[0] == "openSUSE-SLE":
            continue

        # openSUSE-SLE mask
        #    url = f"{url_base}/SUSE_Updates_{repo[0]}_{repo[1]}/repodata/repomd.xml"
        url = f"{url_base}/SUSE_Updates_{repo[0]}_{repo[1]}_{arch}/repodata/repomd.xml"

        try:
            root = ET.fromstring(requests.get(url).text)
            cs = root.find(".//{http://linux.duke.edu/metadata/repo}revision")
        except (
            ET.ParseError,
            requests.ConnectionError,
        ):  # for now, use logger.exception to determine possible exceptions in this code :D
            logger.info("%s: %s not found -- skip incident" % (datetime.now(),url))
            raise NoRepoFoundError
        # TODO: fix handling of requests errors
        except Exception as e:
            logger.exception(e)
            raise e

        if cs is None:
            logger.error("%s's revision is None" % url)
            raise NoRepoFoundError

        rev = int(cs.text)

        if rev > max_rev:
            max_rev = rev
    
    return max_rev


def merge_repohash(hashes: List[str]) -> str:
    m = md5(b"start")

    for h in hashes:
        m.update(h.encode())

    return m.hexdigest()
