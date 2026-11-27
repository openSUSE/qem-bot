# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Repository URL computation for job settings.

Pure functions from a channel's repositories, published product set and architecture to
the repository URLs and product names openQA jobs read.
"""

from __future__ import annotations

import re
from functools import lru_cache
from logging import getLogger
from typing import TYPE_CHECKING

import requests

from openqabot import config
from openqabot.types.channels.slfo import get_product_name
from openqabot.types.types import ChannelType, get_channel_type
from openqabot.utils import retry10_gitea as retried_requests

if TYPE_CHECKING:
    from openqabot.types.types import Repos

log = getLogger("bot.loader.repourl")

VERSION_TOKEN_REGEX = re.compile(r"\d+(?:\.\d+)*")


def _split_repo_dir_name(name: str) -> tuple[str, str]:
    """Split a repository directory name such as `SLES-SAP-16.1-ppc64le` into product and arch."""
    name = name.rstrip("/")
    for suffix in ("-Debug", "-Source"):
        name = name.removesuffix(suffix)
    parts = name.split("-")
    version_index = next((index for index, part in enumerate(parts) if VERSION_TOKEN_REGEX.fullmatch(part)), None)
    return ("-".join(parts[:version_index]), parts[-1]) if version_index else ("", "")


@lru_cache(maxsize=2048)
def published_products(obs_project: str, arch: str) -> frozenset[str]:
    """Return the products that an OBS project publishes for one architecture.

    An empty result also means that the listing could not be read, so callers keep their defaults.
    """
    repository = config.settings.obs_repo_type or "product"
    url = f"{config.settings.obs_download_url}/{obs_project.replace(':', ':/')}/{repository}/repo/"
    try:
        response = retried_requests.get(url, params={"jsontable": 1})
        response.raise_for_status()
        names = [entry["name"] for entry in response.json()["data"]]
    except (KeyError, TypeError, ValueError, requests.exceptions.RequestException) as e:
        log.debug("Could not read the published products of %s: %s", obs_project, e)
        return frozenset()
    return frozenset(
        product for product, entry_arch in map(_split_repo_dir_name, names) if product and entry_arch == arch
    )


def product_names_for_channel(repo: Repos, product_repo: list[str] | str | None) -> list[str]:
    """Return the products whose repos a job reads from a channel's subproject.

    A configured `product_repo` list applies only to subprojects that publish the channel's own
    product, e.g. the `SLES` subproject serves `SLES`, `SLES-HA` and `SLES-SAP` while the
    `SLES-NVIDIA` subproject publishes only `SLES-NVIDIA`. Other channels read the product their
    subproject publishes, without a version embedded in the subproject name, e.g. `SL-Micro` for
    `SL-Micro-6.1`. The previous names stay when the listing is unreadable.
    """
    configured = [product_repo] if isinstance(product_repo, str) else list(product_repo or [])
    own = get_product_name(repo.version) if get_channel_type(repo.product) == ChannelType.SLFO else ""
    if not own or own in configured:
        return configured or [own]
    if not (published := published_products(f"{repo.product}:{repo.version}", repo.arch)):
        return configured or [own]
    if applicable := [product for product in configured if product in published]:
        return applicable
    if own in published:
        return [own]
    if prefix := max((product for product in published if own.startswith(f"{product}-")), key=len, default=""):
        log.debug("Channel %s publishes product %s, not %s", repo.version, prefix, own)
        return [prefix]
    log.debug("Channel %s publishes %s instead of the configured %s", repo.version, sorted(published), configured)
    return [own]


def compute_repo_url_for_job_setting(
    base: str,
    repo: Repos,
    product_repo: list[str] | str | None,
    product_version: str | None,
) -> str:
    """Construct repository URLs for openQA job settings."""
    p_ver = product_version or repo.product_version
    repo_with_opts = repo._replace(product_version=p_ver)
    product_names = product_names_for_channel(repo, product_repo)
    return ",".join(repo_with_opts.compute_url(base, p, path="") for p in product_names)
