# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

from hashlib import md5
from logging import getLogger

import requests
from lxml import etree
from requests.exceptions import RetryError

from openqabot.config import OBS_DOWNLOAD_URL, OBS_PRODUCTS
from openqabot.errors import NoRepoFoundError
from openqabot.utils import retry5 as retried_requests

from . import gitea

log = getLogger("bot.loader.repohash")


def get_max_revision(
    repos: list[tuple[str, str]],
    arch: str,
    project: str,
    product_name: str | None = None,
    product_version: str | None = None,
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
                        "Repository %s skipped: Product %s is not in considered products",
                        repo[1],
                        product_name,
                    )
                    continue
            if product_version is not None:
                repo = (repo[0], repo[1], product_version)
            url = gitea.compute_repo_url(OBS_DOWNLOAD_URL, product_name, repo, arch)
            log.debug("Computing RepoHash for %s from %s", repo[1], url)
        # openSUSE and SLE incidents have different handling of architecture
        elif repo[0].startswith("openSUSE"):
            url = f"{url_base}/SUSE_Updates_{repo[0]}_{repo[1]}/repodata/repomd.xml"
        else:
            url = f"{url_base}/SUSE_Updates_{repo[0]}_{repo[1]}_{arch}/repodata/repomd.xml"

        try:
            root = etree.fromstring(retried_requests.get(url).content)
            cs = root.find(".//{http://linux.duke.edu/metadata/repo}revision")
        except (
            etree.ParseError,
            requests.ConnectionError,
            requests.HTTPError,
            RetryError,
        ) as e:  # for now, use logger.exception to determine possible exceptions in this code :D
            log.info("Incident skipped: RepoHash metadata not found at %s", url)
            raise NoRepoFoundError from e

        if cs is None:
            log.error("RepoHash calculation failed: No revision tag found in %s", url)
            raise NoRepoFoundError
        max_rev = max(max_rev, int(str(cs.text)))

    return max_rev


def merge_repohash(hashes: list[str]) -> str:
    return md5(b"start" + "".join(hashes).encode()).hexdigest()  # noqa: S324 hashlib-insecure-hash-function
