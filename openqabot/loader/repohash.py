# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from hashlib import md5
from logging import getLogger
from typing import List, Optional, Tuple
from xml.etree import ElementTree as ET

import requests
from requests.exceptions import RetryError

from .. import OBS_DOWNLOAD_URL, OBS_PRODUCTS
from ..errors import NoRepoFoundError
from ..utils import retry5 as retried_requests
from . import gitea

log = getLogger("bot.loader.repohash")


def get_max_revision(
    repos: List[Tuple[str, str]],
    arch: str,
    project: str,
    product_name: Optional[str] = None,
    product_version: Optional[str] = None,
) -> int:
    max_rev = 0
    url_base = f"{OBS_DOWNLOAD_URL}/{project.replace(':', ':/')}"

    for repo in repos:
        # handle URLs for SLFO specifically
        if project == "SLFO":
            if product_name is None:
                product_name = gitea.get_product_name(repo[1])
                if product_name not in OBS_PRODUCTS:
                    log.info(
                        "skipping repo '%s' as product '%s' is not considered",
                        repo[1],
                        product_name,
                    )
                    continue
            if product_version is not None:
                repo = (repo[0], repo[1], product_version)
            url = gitea.compute_repo_url(OBS_DOWNLOAD_URL, product_name, repo, arch)
            log.debug("computing repohash for '%s' via: %s", repo[1], url)
        # openSUSE and SLE incidents have different handling of architecture
        elif repo[0].startswith("openSUSE"):
            url = f"{url_base}/SUSE_Updates_{repo[0]}_{repo[1]}/repodata/repomd.xml"
        else:
            url = f"{url_base}/SUSE_Updates_{repo[0]}_{repo[1]}_{arch}/repodata/repomd.xml"

        try:
            root = ET.fromstring(retried_requests.get(url).text)
            cs = root.find(".//{http://linux.duke.edu/metadata/repo}revision")
        except (
            ET.ParseError,
            requests.ConnectionError,
            requests.HTTPError,
            RetryError,
        ) as e:  # for now, use logger.exception to determine possible exceptions in this code :D
            log.info("%s not found -- skipping incident" % url)
            raise NoRepoFoundError from e
        except Exception as e:
            log.exception(e)
            raise e

        if cs is None:
            log.error("%s's revision is None", url)
            raise NoRepoFoundError
        max_rev = max(max_rev, int(str(cs.text)))

    return max_rev


def merge_repohash(hashes: List[str]) -> str:
    m = md5(b"start")

    for h in hashes:
        m.update(h.encode())

    return m.hexdigest()
