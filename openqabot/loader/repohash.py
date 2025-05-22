# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from hashlib import md5
from logging import getLogger
from typing import List, Tuple
from xml.etree import ElementTree as ET

from requests import ConnectionError, HTTPError
from requests.exceptions import RetryError

from .. import OBS_DOWNLOAD_URL
from ..errors import NoRepoFoundError
from ..utils import retry5 as requests

log = getLogger("bot.loader.repohash")


def get_max_revision(
    repos: List[Tuple[str, str]],
    arch: str,
    project: str,
) -> int:
    max_rev = 0

    url_base = f"{OBS_DOWNLOAD_URL}/{project.replace(':',':/')}"

    for repo in repos:
        # handle URLs for SLFO specifically
        if project == "SLFO":
            url = f"{OBS_DOWNLOAD_URL}/{repo[0].replace(':',':/')}:/{repo[1].replace(':',':/')}/standard/repodata/repomd.xml"
        # openSUSE and SLE incidents have different handling of architecture
        elif repo[0].startswith("openSUSE"):
            url = f"{url_base}/SUSE_Updates_{repo[0]}_{repo[1]}/repodata/repomd.xml"
        else:
            url = f"{url_base}/SUSE_Updates_{repo[0]}_{repo[1]}_{arch}/repodata/repomd.xml"

        try:
            root = ET.fromstring(requests.get(url).text)
            cs = root.find(".//{http://linux.duke.edu/metadata/repo}revision")
        except (
            ET.ParseError,
            ConnectionError,
            HTTPError,
            RetryError,
        ):  # for now, use logger.exception to determine possible exceptions in this code :D
            log.info("%s not found -- skipping incident" % url)
            raise NoRepoFoundError
        except Exception as e:
            log.exception(e)
            raise e

        if cs is None:
            log.error("%s's revision is None", url)
            raise NoRepoFoundError

        rev = int(str(cs.text))

        max_rev = max(max_rev, rev)

    if max_rev == 0:
        raise NoRepoFoundError

    return max_rev


def merge_repohash(hashes: List[str]) -> str:
    m = md5(b"start")

    for h in hashes:
        m.update(h.encode())

    return m.hexdigest()
