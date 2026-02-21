# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Repository hash loader."""

from __future__ import annotations

from hashlib import md5
from logging import getLogger
from typing import TYPE_CHECKING, NamedTuple

import requests
from lxml import etree  # type: ignore[unresolved-import]
from requests.exceptions import RetryError

from openqabot import config
from openqabot.errors import NoRepoFoundError
from openqabot.utils import retry5 as retried_requests

from . import gitea

if TYPE_CHECKING:
    from collections.abc import Sequence

    from openqabot.types.types import Repos

log = getLogger("bot.loader.repohash")


class RepoOptions(NamedTuple):
    """Options for repository hash calculation."""

    product_name: str | None = None
    product_version: str | None = None
    submission_id: str | None = None


def get_max_revision(
    repos: Sequence[Repos],
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

    for repo in repos:
        product_name = options.product_name or gitea.get_product_name(repo.version)
        product_version = options.product_version or repo.product_version
        repo_with_opts = repo._replace(product_version=product_version)
        url = repo_with_opts.compute_url(config.settings.obs_download_url, product_name, arch, project=project)
        log.debug("Computing RepoHash for %s from %s", repo.version, url)

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
