# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Repository hash loader."""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import md5
from logging import getLogger
from typing import NamedTuple

import requests
from lxml import etree  # type: ignore[unresolved-import]
from requests.exceptions import RetryError

from openqabot.config import OBS_DOWNLOAD_URL
from openqabot.errors import NoRepoFoundError
from openqabot.utils import retry5 as retried_requests

from . import gitea

log = getLogger("bot.loader.repohash")


class RepoOptions(NamedTuple):
    """Options for repository hash calculation."""

    product_name: str | None = None
    product_version: str | None = None
    submission_id: str | None = None


def get_max_revision(
    repos: Sequence[tuple[str, ...]],
    arch: str,
    project: str,
    options: RepoOptions | None = None,
) -> int:
    """Calculate the maximum repository revision for a submission."""
    max_rev = 0
    options = options or RepoOptions()
    sub_msg = (
        f"Submission {options.submission_id} skipped"
        if options.submission_id
        else f"Submission for project {project} skipped"
    )

    url_base = f"{OBS_DOWNLOAD_URL}/{project.replace(':', ':/')}"

    for repo in repos:
        # handle URLs for SLFO specifically
        if project == "SLFO":
            repo_tuple = repo
            if options.product_version is not None:
                repo_tuple = (repo[0], repo[1], options.product_version)
            url = gitea.compute_repo_url(
                OBS_DOWNLOAD_URL, options.product_name or gitea.get_product_name(repo[1]), repo_tuple, arch
            )
            log.debug("Computing RepoHash for %s from %s", repo[1], url)
        # openSUSE and SLE submissions have different handling of architecture
        elif repo[0].startswith("openSUSE"):
            url = f"{url_base}/SUSE_Updates_{repo[0]}_{repo[1]}/repodata/repomd.xml"
        else:
            url = f"{url_base}/SUSE_Updates_{repo[0]}_{repo[1]}_{arch}/repodata/repomd.xml"

        try:
            req = retried_requests.get(url)
            if not req.ok:
                log.info("Submission skipped: RepoHash metadata not found at %s", url)
                continue
            root = etree.fromstring(req.content)
            cs = root.find(".//{http://linux.duke.edu/metadata/repo}revision")
        except (
            etree.ParseError,
            requests.ConnectionError,
            requests.HTTPError,
            RetryError,
        ) as e:  # for now, use logger.exception to determine possible exceptions in this code :D
            log.info("%s: RepoHash metadata not found at %s", sub_msg, url)
            raise NoRepoFoundError from e

        if cs is None:
            log.info("%s: RepoHash calculation failed, no revision tag found in %s", sub_msg, url)
            raise NoRepoFoundError
        max_rev = max(max_rev, int(str(cs.text)))

    return max_rev


def merge_repohash(hashes: list[str]) -> str:
    """Merge multiple repohashes into a single MD5 hash."""
    return md5(b"start" + "".join(hashes).encode(), usedforsecurity=False).hexdigest()
