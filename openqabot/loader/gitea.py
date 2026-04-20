# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Gitea loader."""

from __future__ import annotations

import json
import urllib.error
from concurrent import futures
from contextlib import suppress
from dataclasses import dataclass, field
from functools import lru_cache
from http import HTTPStatus
from logging import getLogger
from typing import TYPE_CHECKING, Any, cast

import osc.conf as osc_conf
import osc.core as osc_core
import osc.util.xml as osc_xml
import requests
from lxml import etree  # ty: ignore[unresolved-import]
from osc.connection import http_GET
from osc.core import MultibuildFlavorResolver

from openqabot import config
from openqabot.errors import NoRepoFoundError
from openqabot.types.pullrequest import PullRequest
from openqabot.types.gitea import RepoConfig
from openqabot.types.types import Repos
from openqabot.utils import get_repo_url
from openqabot.utils import retry10 as retried_requests

if TYPE_CHECKING:
    from collections.abc import Iterator


from openqabot.loader.gitea_utils import (
    ARCHS,
    OBS_PROJECT_SHOW_REGEX,
    URL_FINDALL_REGEX,
    _approval_identifiers,
    _extract_version,
    _is_bot_approval_comment,
    changed_files_url,
    comments_url,
    get_json,
    get_product_name,
    get_product_name_and_version_from_scmsync,
    iter_gitea_items,
    make_token_header,
    patch_json,
    post_json,
    read_json_file,
    read_json_file_list,
    read_utf8,
    read_xml,
    reviews_url,
)

# Re-exporting for other modules
__all__ = [
    "BuildResults",
    "add_build_results",
    "add_channel_for_build_result",
    "add_comments_and_referenced_build_results",
    "add_packages_from_files",
    "add_packages_from_patchinfo",
    "add_reviews",
    "approve_pr",
    "compute_repo_url_for_job_setting",
    "determine_relevant_archs_from_multibuild_info",
    "generate_repo_url",
    "get_gitea_staging_config",
    "get_multibuild_data",
    "get_name",
    "get_open_prs",
    "get_product_version_from_repo_listing",
    "get_submissions_from_open_prs",
    "is_build_acceptable_and_log_if_not",
    "is_build_result_relevant",
    "is_review_requested_by",
    "make_submission_from_gitea_pr",
    "make_token_header",
    "patch_json",
    "post_json",
    "read_json_file",
    "read_utf8",
    "read_xml",
    "review_pr",
    "reviews_url",
    "verify_repo_exists",
]

log = getLogger("bot.loader.gitea")


@dataclass
class BuildResults:
    """Results of a build."""

    projects: set[str] = field(default_factory=set)
    successful: set[str] = field(default_factory=set)
    unpublished: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    unavailable: set[str] = field(default_factory=set)

    def update_submission(self, submission: dict[str, Any]) -> None:
        """Update submission with aggregated build results."""
        submission.update({
            "failed_or_unpublished_packages": sorted(self.failed | self.unpublished | self.unavailable),
            "successful_packages": sorted(self.successful),
        })

        if "channels" not in submission:
            submission["channels"] = []

        for result in sorted(self.projects):
            if result not in submission["channels"]:
                submission["channels"].append(result)

        # fallback scminfo if only one product is configured
        obs_products = config.settings.obs_products_set
        if "scminfo" not in submission and len(obs_products) == 1 and "all" not in obs_products:
            submission["scminfo"] = submission.get(f"scminfo_{next(iter(obs_products))}", "")


def compute_repo_url_for_job_setting(
    base: str,
    repo: Repos,
    product_repo: list[str] | str | None,
    product_version: str | None,
) -> str:
    """Construct repository URLs for openQA job settings."""
    product_names = get_product_name(repo.version) if product_repo is None else product_repo
    p_ver = product_version or repo.product_version
    product_list = product_names if isinstance(product_names, list) else [product_names]
    repo_with_opts = repo._replace(product_version=p_ver)
    return ",".join(repo_with_opts.compute_url(base, p, path="", project="SLFO") for p in product_list)


def _fetch_all_prs(repo: str, token: dict[str, str]) -> list[PullRequest]:
    try:
        return [
            pr
            for pr_json in iter_gitea_items(f"repos/{repo}/pulls?state=open", token)
            if (pr := PullRequest.from_json(pr_json)) is not None
        ]
    except (requests.exceptions.RequestException, json.JSONDecodeError):
        log.exception("Gitea API error: Could not fetch open PRs from %s", repo)
    return []


def get_open_prs(token: dict[str, str], repo: str, *, number: int | None) -> list[PullRequest]:
    """Fetch open PRs from a Gitea repository."""
    log.debug("Fetching open PRs from '%s'", repo)
    if number is None:
        return _fetch_all_prs(repo, token)
    return _get_single_pr(token, repo, number)


def _get_single_pr(token: dict[str, str], repo: str, number: int) -> list[PullRequest]:
    try:
        # https://docs.gitea.com/api/1.25/#tag/repository/operation/repolistPullRequests
        if pr := PullRequest.from_json(cast("dict[str, Any]", get_json(f"repos/{repo}/pulls/{number}", token))):
            return [pr]
    except (requests.exceptions.RequestException, json.JSONDecodeError) as ex:
        log.error("PR git:%s ignored: %s", number, ex, exc_info=True)  # noqa: G201
    return []


def review_pr(  # noqa: PLR0913
    token: dict[str, str],
    repo_name: str,
    pr_number: int,
    msg: str,
    commit_id: str,
    *,
    approve: bool = True,
) -> None:
    """Post a review or comment on a Gitea PR."""
    bot_user = config.settings.git_review_bot_user
    if bot_user:
        review_url = comments_url(repo_name, pr_number)
        review_cmd, commit_str = _approval_identifiers(bot_user, commit_id, approve=approve)
        review_data = {"body": f"{review_cmd}\n{msg}\n{commit_str}"}
    else:
        review_url = reviews_url(repo_name, pr_number)
        review_data = {
            "body": msg,
            "comments": [],
            "commit_id": commit_id,
            "event": "APPROVED" if approve else "REQUEST_CHANGES",
        }
    post_json(review_url, token, review_data)


def approve_pr(token: dict[str, str], repo_name: str, pr_number: int, commit_id: str, msg: str) -> bool:
    """Approve a PR on Gitea using its repository name and commit ID."""
    try:
        bot_user = config.settings.git_review_bot_user
        if bot_user:
            comments = iter_gitea_items(comments_url(repo_name, pr_number), token)
            if any(_is_bot_approval_comment(c, bot_user, commit_id) for c in comments):
                log.info("PR %s already approved via comment for commit %s", pr_number, commit_id)
                return True
        else:
            reviews = iter_gitea_items(reviews_url(repo_name, pr_number), token)
            if any(
                (r.get("commit_id"), r.get("state")) == (commit_id, "APPROVED") and is_review_requested_by(r)
                for r in reviews
            ):
                log.info("PR %s already approved for commit %s", pr_number, commit_id)
                return True

        log.info("PR %s approved for commit %s", pr_number, commit_id)
        review_pr(token, repo_name, pr_number, msg, commit_id, approve=True)
    except Exception:
        log.exception("Gitea API error: Failed to approve PR %s", pr_number)
        return False
    return True


def get_name(review: dict[str, Any], of: str, via: str) -> str:
    """Extract a name from a Gitea review entity."""
    entity = review.get(of)
    return entity.get(via, "") if entity is not None else ""


def is_review_requested_by(
    review: dict[str, Any],
    users: tuple[str | None, ...] | None = None,
) -> bool:
    """Check if a review was requested by specific users or groups."""
    if users is None:
        users = (config.settings.obs_group, config.settings.git_review_bot_user)
    user_specifications = (
        get_name(review, "user", "login"),  # review via our bot account or review bot
        get_name(review, "team", "name"),  # review request for team bot is part of
    )
    return any(user in user_specifications for user in users)


def add_reviews(submission: dict[str, Any], reviews: list[Any]) -> int:
    """Process PR reviews and update submission status."""
    qam_pending, qam_blocking, qam_approved = 0, 0, 0

    qam_reviews = [r for r in open_reviews if is_review_requested_by(r)]
    for r in qam_reviews:
        state = r.get("state", "")
        qam_pending += state in {"PENDING", "REQUEST_REVIEW"}
        qam_blocking += state in {"REQUEST_CHANGES", "REQUEST_REVIEW"}
        qam_approved += state == "APPROVED"

    other_reviews = [r for r in open_reviews if not is_review_requested_by(r)]
    other_pending = any(r.get("state", "") in {"PENDING", "REQUEST_REVIEW"} for r in other_reviews)

    submission.update({
        "approved": qam_approved > 0 and qam_blocking == 0,
        "inReviewQAM": qam_pending > 0,
        "inReview": other_pending or qam_pending > 0,
    })
    return len(qam_reviews)


def _fetch_repo_data(url: str) -> list[dict[str, Any]]:
    """Fetch repository listing data from OBS."""
    try:
        r = retried_requests.get(url, params={"jsontable": 1})
        r.raise_for_status()
        return cast("list[dict[str, Any]]", r.json()["data"])
    except requests.exceptions.HTTPError as e:
        log.warning("Repo ignored: Could not query repository '%s': %s", url, e)
    except (json.JSONDecodeError, requests.exceptions.JSONDecodeError) as e:
        log.info("Invalid JSON document at '%s', ignoring: %s", url, e)
    except requests.exceptions.RequestException as e:
        log.warning("Product version unresolved: Could not read from '%s': %s", url, e)
    return []


@lru_cache(maxsize=512)
def get_product_version_from_repo_listing(
    project: str, product_name: str, repository: str, obs_download_url: str
) -> str:
    """Determine the product version by inspecting an OBS repository listing."""
    project_path = project.replace(":", ":/")
    url = f"{obs_download_url}/{project_path}/{repository}/repo"
    start = f"{product_name}-"
    data = _fetch_repo_data(url)
    versions = (_extract_version(entry["name"], start) for entry in data if entry["name"].startswith(start))
    return next((v for v in versions if v), "")


def verify_repo_exists(
    target: Repos,
    product_version: str,
    config: RepoConfig,
) -> bool:
    """Check if the repository actually exists for the given architecture via HTTP HEAD request."""
    if not product_version:
        return True
    repo_url = get_repo_url(target, product_version, config)
    with suppress(requests.exceptions.RequestException):
        response = retried_requests.head(repo_url, allow_redirects=True)
        if response.status_code == HTTPStatus.NOT_FOUND:
            log.debug("Repo %s not found, skipping channel", repo_url)
            return False
        log.debug("Repo %s returned %s, allowing channel", repo_url, response.status_code)
        return response.ok
    log.info("HTTP check failed for repo %s, allowing channel", repo_url)
    return True


def _get_scmsync_version(res: etree._Element) -> str:
    """Extract product version from scmsync element."""
    for text in (e.text for e in res.findall("scmsync") if e.text):
        _, pv = get_product_name_and_version_from_scmsync(text)
        if pv:
            return pv
    return ""


def _get_product_version(
    res: etree._Element,
    target: Repos,
    config: RepoConfig,
) -> str:
    """Extract product version from scmsync element or repository listing."""
    product_version = _get_scmsync_version(res)

    # read product version from directory listing if the project is for a concrete product
    if (
        not product_version
        and target.version
        and config.obs_products
        and ("all" in config.obs_products or target.version in config.obs_products)
    ):
        product_version = get_product_version_from_repo_listing(
            target.product, target.version, res.get("repository"), config.obs_download_url
        )

    return product_version


def add_channel_for_build_result(
    target: Repos,
    res: etree._Element,
    projects: set[str],
    *,
    config: RepoConfig,
) -> str:
    """Construct a channel string for a build result and add it to the project set."""
    channel = f"{target.product}:{target.arch}"
    if target.arch == "local":
        return channel

    product_version = _get_product_version(res, target, config)

    # append product version to channel if known; otherwise skip channel if this is for a concrete product
    if product_version:
        channel += f"#{product_version}"
    elif target.version:
        log.debug(
            "Channel skipped: Product version for build result %s:%s could not be determined",
            target.product,
            target.arch,
        )
        return channel

    if not product_version or verify_repo_exists(target, product_version, config):
        projects.add(channel)
    return channel


def _update_scminfo(submission: dict[str, Any], res: etree._Element, project: str, product: str) -> None:
    """Update SCM info in the submission dict."""
    scm_key = f"scminfo_{product}" if product else "scminfo"
    for found in {e.text for e in res.findall("scminfo") if e.text}:
        existing = submission.get(scm_key)
        if existing and found != existing:
            log.warning(
                "PR git:%s: Inconsistent SCM info for project %s: found '%s' vs '%s'",
                submission["number"],
                project,
                found,
                existing,
            )
        else:
            submission[scm_key] = found


def _update_build_statuses(res: etree._Element, results: BuildResults) -> None:
    """Update successful and failed packages based on build status."""
    statuses = res.findall("status")
    results.successful.update(s.get("package") for s in statuses if s.get("code") == "succeeded")
    results.failed.update(s.get("package") for s in statuses if s.get("code") not in {"excluded", "succeeded"})


def add_build_result(
    submission: dict[str, Any],
    res: etree._Element,
    results: BuildResults,
) -> None:
    """Process a single build result and update submission and results."""
    project = res.get("project")
    product = get_product_name(project)

    _update_scminfo(submission, res, project, product)

    repo_config = RepoConfig(
        repo_type=config.settings.obs_repo_type or "product",
        download_base_url=config.settings.download_base_url,
        obs_download_url=config.settings.obs_download_url,
        repo_mirror_host=config.settings.repo_mirror_host,
        obs_products=config.settings.obs_products_set,
    )
    target = Repos(product=project, version=product, arch=res.get("arch"))
    channel = add_channel_for_build_result(target, res, results.projects, config=repo_config)
    if "all" not in config.settings.obs_products_set and product not in config.settings.obs_products_set:
        return

    if res.get("state") != "published":
        results.unpublished.add(channel)
        return

    _update_build_statuses(res, results)


def get_multibuild_data(obs_project: str) -> str:
    """Fetch multibuild configuration data for an OBS project."""
    r = MultibuildFlavorResolver(config.settings.obs_url, obs_project, "000productcompose")
    return cast("str", r.get_multibuild_data())


def _get_multibuild_xml(obs_project: str, *, dry: bool) -> str | None:
    """Fetch multibuild XML data."""
    if dry:
        return read_utf8(f"_multibuild-124-{obs_project}.xml")
    try:
        return get_multibuild_data(obs_project)
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        log.warning("Could not determine relevant architectures for %s: %s", obs_project, e)
    return None


def determine_relevant_archs_from_multibuild_info(obs_project: str, *, dry: bool) -> set[str] | None:
    """Determine which architectures are relevant for a product based on multibuild data."""
    product_name = get_product_name(obs_project)
    if not product_name:
        return None
    product_prefix = product_name.replace("SL-", "sle_").replace(":", "_").lower() + "_"
    prefix_len = len(product_prefix)
    multibuild_data = _get_multibuild_xml(obs_project, dry=dry)
    if not multibuild_data:
        return None

    # determine from the flavors we got what architectures are actually expected to be present
    flavors = MultibuildFlavorResolver.parse_multibuild_data(multibuild_data)
    relevant_archs = {
        flavor[prefix_len:] for flavor in flavors if flavor.startswith(product_prefix) and flavor[prefix_len:] in ARCHS
    }
    log.debug("Relevant archs for %s: %s", obs_project, sorted(relevant_archs))
    return relevant_archs


def is_build_result_relevant(res: etree._Element, relevant_archs: set[str] | None) -> bool:
    """Check if a build result is relevant for the current product and architecture."""
    if config.settings.obs_repo_type and res.get("repository") != config.settings.obs_repo_type:
        return False
    arch = res.get("arch")
    return arch == "local" or relevant_archs is None or arch in relevant_archs


def _get_project_results(obs_project: str, *, dry: bool, results: BuildResults) -> list[etree._Element]:
    """Fetch build results for an OBS project."""
    build_info_url = osc_core.makeurl(config.settings.obs_url, ["build", obs_project, "_result"])
    if dry:
        return read_xml("build-results-124-" + obs_project).getroot().findall("result")
    try:
        return osc_xml.xml_parse(http_GET(build_info_url)).getroot().findall("result")
    except urllib.error.HTTPError:
        results.unavailable.add(obs_project)
        log.info("Build results for project %s unreadable, skipping: %s", obs_project, build_info_url)
        return []


def _process_obs_url(
    url: str,
    submission: dict[str, Any],
    *,
    dry: bool,
    results: BuildResults,
) -> None:
    """Process an OBS URL and update submission build results."""
    if not (project_match := OBS_PROJECT_SHOW_REGEX.search(url)):
        return
    obs_project = project_match.group(1)
    log.debug("Checking OBS project %s", obs_project)
    relevant_archs = determine_relevant_archs_from_multibuild_info(obs_project, dry=dry)

    for res in _get_project_results(obs_project, dry=dry, results=results):
        if is_build_result_relevant(res, relevant_archs):
            add_build_result(submission, res, results)


def add_build_results(submission: dict[str, Any], obs_urls: list[str], *, dry: bool) -> None:
    """Aggregate build results from multiple OBS URLs into a submission."""
    results = BuildResults()

    for url in obs_urls:
        _process_obs_url(url, submission, dry=dry, results=results)

    if results.unpublished:
        log.info(
            "PR git:%i: Some repos not published yet: %s",
            submission["number"],
            ", ".join(results.unpublished),
        )
    if results.failed:
        log.info("PR git:%i: Some packages failed: %s", submission["number"], ", ".join(results.failed))

    results.update_submission(submission)


def add_comments_and_referenced_build_results(
    submission: dict[str, Any],
    comments: list[Any],
    *,
    dry: bool,
) -> None:
    """Find and process build result URLs from bot comments on a PR."""
    bot_comments = [
        comment for comment in comments if comment["user"]["username"] == config.settings.git_obs_staging_bot_user
    ]
    if not bot_comments:
        return

    obs_urls = {url for comment in bot_comments for url in URL_FINDALL_REGEX.findall(comment["body"])}

    if obs_urls:
        add_build_results(submission, sorted(obs_urls), dry=dry)
    else:
        log.warning(
            "PR git:%s: No OBS URLs found in comments from %s",
            submission["number"],
            config.settings.git_obs_staging_bot_user,
        )


def get_gitea_staging_config(token: dict[str, str]) -> dict:
    """Get content of staging.config file from repository defined in settings.

    Args:
        token (dict[str, str]): security token for Gitea API

    Returns:
        dict: JSON content of staging.config

    """
    response = retried_requests.get(
        config.settings.gitea_staging_config_url,
        verify=False,
        headers=token,
    )
    response.raise_for_status()
    return response.json()


def generate_repo_url(pullrequest: PullRequest, staging_config_qa_labels: dict[str, str], project: str) -> str:
    """Generate repository URL for certain pull request.

    Args:
        pullrequest (PullRequest): pull request for which URL needs to be generated
        staging_config_qa_labels (dict[str, str]): List of labels identifying
                                                    PRs needed testing taken from staging.config
        project (str): "StagingProject" value taken from staging.config file

    Returns:
        str: URL pointing to a folder with iso images generated for certain pullrequest

    Raises:
        NoRepoFoundError: raised when required_labels has more than one match in staging.config

    """
    common_labels = set(staging_config_qa_labels.keys()) & pullrequest.labels

    if len(common_labels) != 1:
        log.error("Expected exactly one matching label but found %d: %s", len(common_labels), common_labels)
        raise NoRepoFoundError

    label = staging_config_qa_labels[common_labels.pop()]
    return f"{config.settings.obs_download_url}/{project}:/{pullrequest.number}:/{label}/product/iso"


def add_packages_from_patchinfo(
    submission: dict[str, Any],
    token: dict[str, str],
    patch_info_url: str,
    *,
    dry: bool,
) -> None:
    """Extract package names from a _patchinfo file URL."""
    if dry:
        patch_info = read_xml("patch-info")
    else:
        try:
            response = retried_requests.get(patch_info_url, verify=not config.settings.insecure, headers=token)
            response.raise_for_status()
            patch_info = etree.fromstring(response.content)
        except (etree.ParseError, requests.RequestException) as e:
            log.info("Failed to parse patchinfo from %s: %s", patch_info_url, e)
            return

    submission["packages"].extend(res.text for res in patch_info.findall("package"))


def add_packages_from_files(submission: dict[str, Any], token: dict[str, str], files: list[Any], *, dry: bool) -> None:
    """Extract packages from all relevant files in a PR."""
    for file_info in files:
        file_name = file_info.get("filename", "").split("/")[-1]
        raw_url = file_info.get("raw_url")
        if file_name == "_patchinfo" and raw_url is not None:
            add_packages_from_patchinfo(submission, token, raw_url, dry=dry)


def is_build_acceptable_and_log_if_not(submission: dict[str, Any], number: int) -> bool:
    """Check if all packages in a submission have been built and published successfully."""
    failed_or_unpublished_packages = len(submission["failed_or_unpublished_packages"])
    if failed_or_unpublished_packages > 0:
        log.info("Skipping PR git:%i: Not all packages succeeded or published", number)
        return False
    if len(submission["successful_packages"]) < 1:
        info = "Skipping PR git:%i: No packages have been built/published (there are %i failed/unpublished packages)"
        log.info(info, number, failed_or_unpublished_packages)
        return False
    return True


def _fetch_details(
    project: str, number: int, token: dict[str, str], *, dry: bool
) -> tuple[list[Any], list[Any], list[Any]]:
    if dry:
        if number == 124:  # noqa: PLR2004
            return (
                read_json_file_list("reviews-124"),
                read_json_file_list("comments-124"),
                read_json_file_list("files-124"),
            )
        return [], [], []
    return (
        list(iter_gitea_items(reviews_url(project, number), token)),
        list(iter_gitea_items(comments_url(project, number), token)),
        list(iter_gitea_items(changed_files_url(project, number), token)),
    )


def _init_submission_dict(pr: PullRequest) -> dict[str, Any]:
    """Initialize a submission dictionary with default values from a PR."""
    return {
        "number": pr.number,
        "project": pr.project,
        # "Emergency Maintenance Update", a flag used to raise a priority in scheduler
        # see openqabot/types/incidents.py#L227
        "emu": False,
        "isActive": pr.is_active(),
        "inReviewQAM": False,
        "inReview": False,
        "approved": False,
        # `_patchinfo` should contain something like <embargo_date>2025-05-01</embargo_date> if embargo applies
        "embargoed": False,
        "priority": 0,  # only used for display purposes on the dashboard, maybe read from a label at some point
        "rr_number": None,
        "packages": [],
        "channels": [],
        "url": pr.url,
        "type": "git",
    }


def _validate_submission(
    submission: dict[str, Any],
    number: int,
    *,
    only_successful_builds: bool,
) -> bool:
    """Validate if the submission has channels, acceptable builds, and packages."""
    if not submission["channels"]:
        log.info("PR git:%s skipped: No channels found", number)
        return False
    return not (only_successful_builds and not is_build_acceptable_and_log_if_not(submission, number))
def make_submission_from_gitea_pr(
    pr: PullRequest,
    token: dict[str, str],
    *,
    only_successful_builds: bool,
    only_requested_prs: bool,
    dry: bool,
) -> dict[str, Any] | None:
    """Create a dashboard-compatible submission record from a Gitea PR."""
    log.debug("Fetching info for PR git:%s from Gitea", pr.number)
    try:
        submission = _init_submission_dict(pr)
        reviews, comments, files = _fetch_details(pr.project, pr.number, token, dry=dry)

        if add_reviews(submission, reviews) < 1 and only_requested_prs:
            log.info("PR git:%s skipped: No reviews by %s", pr.number, config.settings.obs_group)
            return None

        add_comments_and_referenced_build_results(submission, comments, dry=dry)
        if not _validate_submission(submission, pr.number, only_successful_builds=only_successful_builds):
            return None
        add_packages_from_files(submission, token, files, dry=dry)
        if not submission["packages"]:
            log.info("PR git:%s skipped: No packages found", pr.number)
            return None

    except Exception:
        log.exception("Gitea API error: Unable to process PR git:%s", pr.number)
        return None
    return submission


def get_submissions_from_open_prs(
    open_prs: list[PullRequest],
    token: dict[str, str],
    *,
    only_successful_builds: bool,
    only_requested_prs: bool,
    dry: bool,
) -> list[dict[str, Any]]:
    """Convert a list of open Gitea PRs into dashboard submissions."""
    submissions = []

    # configure osc to be able to request build info from OBS
    osc_conf.get_config(override_apiurl=config.settings.obs_url)

    with futures.ThreadPoolExecutor() as executor:
        future_sub = [
            executor.submit(
                make_submission_from_gitea_pr,
                pr,
                token,
                only_successful_builds=only_successful_builds,
                only_requested_prs=only_requested_prs,
                dry=dry,
            )
            for pr in open_prs
        ]
        submissions = (future.result() for future in futures.as_completed(future_sub))
        return [sub for sub in submissions if sub]
