# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Gitea loader."""

from __future__ import annotations

import json
import re
import urllib.error
from collections import Counter
from concurrent import futures
from dataclasses import dataclass, field
from functools import lru_cache
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING, Any

import osc.conf
import osc.core
import osc.util.xml
import requests
import urllib3
import urllib3.exceptions
from lxml import etree  # type: ignore[unresolved-import]
from osc.connection import http_GET
from osc.core import MultibuildFlavorResolver

from openqabot import config
from openqabot.utils import retry10 as retried_requests

if TYPE_CHECKING:
    from openqabot.types.types import Repos

ARCHS = {"x86_64", "aarch64", "ppc64le", "s390x"}

log = getLogger("bot.loader.gitea")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@dataclass
class BuildResults:
    """Results of a build."""

    projects: set[str] = field(default_factory=set)
    successful: set[str] = field(default_factory=set)
    unpublished: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    unavailable: set[str] = field(default_factory=set)


PROJECT_PRODUCT_REGEX = re.compile(r".*:PullRequest:\d+:(.*)")
SCMSYNC_REGEX = re.compile(r".*/products/(.*)#([\d\.]{2,6})$")
VERSION_EXTRACT_REGEX = re.compile(r"[.\d]+")
OBS_PROJECT_SHOW_REGEX = re.compile(r".*/project/show/([^/\s\?\#\)]+)")
# Regex to find all HTTPS URLs, excluding common trailing punctuation like dots or parentheses
# that are likely part of the surrounding text (e.g. at the end of a sentence or in Markdown).
URL_FINDALL_REGEX = re.compile(r"https?://[^\s\?\#\)]*[^\s\?\#\)\.]")


def make_token_header(token: str) -> dict[str, str]:
    """Create the Authorization header for Gitea API requests."""
    return {} if token is None else {"Authorization": "token " + token}


def get_json(query: str, token: dict[str, str], host: str | None = None) -> Any:  # noqa: ANN401
    """Fetch JSON data from Gitea API."""
    host = host or config.settings.gitea_url
    return retried_requests.get(host + "/api/v1/" + query, verify=False, headers=token).json()


def post_json(query: str, token: dict[str, str], post_data: Any, host: str | None = None) -> Any:  # noqa: ANN401
    """Post JSON data to Gitea API."""
    host = host or config.settings.gitea_url
    url = host + "/api/v1/" + query
    res = retried_requests.post(url, verify=False, headers=token, json=post_data)
    if not res.ok:
        log.error("Gitea API error: POST to %s failed: %s", url, res.text)


def read_utf8(name: str) -> str:
    """Read a UTF-8 encoded response file."""
    return Path(f"responses/{name}").read_text(encoding="utf8")


def read_json(name: str) -> Any:  # noqa: ANN401
    """Read a JSON response file."""
    return json.loads(Path(f"responses/{name}.json").read_text(encoding="utf8"))


def read_xml(name: str) -> etree.ElementTree:
    """Read an XML response file."""
    return etree.parse(f"responses/{name}.xml")


def reviews_url(repo_name: str, number: int) -> str:
    """Construct the URL for PR reviews."""
    # https://docs.gitea.com/api/1.20/#tag/repository/operation/repolistPullReviews
    return f"repos/{repo_name}/pulls/{number}/reviews"


def changed_files_url(repo_name: str, number: int) -> str:
    """Construct the URL for PR changed files."""
    # https://docs.gitea.com/api/1.20/#tag/repository/operation/repoGetPullRequestFiles
    return f"repos/{repo_name}/pulls/{number}/files"


def comments_url(repo_name: str, number: int) -> str:
    """Construct the URL for PR comments."""
    # https://docs.gitea.com/api/1.20/#tag/issue/operation/issueCreateComment
    return f"repos/{repo_name}/issues/{number}/comments"


def get_product_name(obs_project: str) -> str:
    """Extract product name from an OBS project name."""
    product_match = PROJECT_PRODUCT_REGEX.search(obs_project)
    return product_match.group(1) if product_match else ""


def get_product_name_and_version_from_scmsync(scmsync_url: str) -> tuple[str, str]:
    """Extract product name and version from an scmsync URL."""
    m = SCMSYNC_REGEX.search(scmsync_url)
    return (m.group(1), m.group(2)) if m else ("", "")


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


def get_open_prs(token: dict[str, str], repo: str, *, dry: bool, number: int | None) -> list[Any]:
    """Fetch open PRs from a Gitea repository."""
    log.debug("Fetching open PRs from '%s'%s", repo, ", dry-run" if dry else "")
    if dry:
        return read_json("pulls")
    if number is not None:
        try:
            pr = get_json(f"repos/{repo}/pulls/{number}", token)
        # Catching RequestException for general API errors, and json's JSONDecodeError
        # for cases where requests might not wrap it in RequestException
        except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError):
            log.exception("PR git:%s ignored: Could not read PR metadata", number)
            return []
        log.debug("PR git:%i: %s", number, pr)
        return [pr]

    def iter_pr_pages() -> Any:  # noqa: ANN401
        """Iterate through all pages of open PRs.

        Yields:
            Lists of open PRs.

        """
        page = 1
        while True:
            # https://docs.gitea.com/api/1.20/#tag/repository/operation/repolistPullRequests
            prs_on_page = get_json(f"repos/{repo}/pulls?state=open&page={page}", token)
            if not isinstance(prs_on_page, list) or not prs_on_page:
                return
            yield prs_on_page
            page += 1

    try:
        return [pr for page in iter_pr_pages() for pr in page]
    except requests.exceptions.JSONDecodeError:
        log.exception("Gitea API error: Invalid JSON received for open PRs")
        return []
    except requests.exceptions.RequestException:
        log.exception("Gitea API error: Could not fetch open PRs")
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
    if config.settings.git_review_bot_user:
        review_url = comments_url(repo_name, pr_number)
        review_cmd = f"@{config.settings.git_review_bot_user}: "
        review_cmd += "approved" if approve else "decline"
        review_data = {"body": f"{review_cmd}\n{msg}\nTested commit: {commit_id}"}
    else:
        review_url = reviews_url(repo_name, pr_number)
        review_data = {
            "body": msg,
            "comments": [],
            "commit_id": commit_id,
            "event": "APPROVED" if approve else "REQUEST_CHANGES",
        }
    post_json(review_url, token, review_data)


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
    pending_states = {"PENDING", "REQUEST_REVIEW"}
    open_reviews = [r for r in reviews if not r.get("dismissed", True)]
    qam_states = [r.get("state", "") for r in open_reviews if is_review_requested_by(r)]
    has_other_pending = any(r.get("state", "") in pending_states for r in open_reviews if not is_review_requested_by(r))
    counts = Counter(qam_states)
    qam_pending = counts["PENDING"] + counts["REQUEST_REVIEW"]
    qam_blocking = counts["REQUEST_CHANGES"] + counts["REQUEST_REVIEW"]
    submission["approved"] = (counts["APPROVED"] > 0) and (qam_blocking == 0)
    submission["inReviewQAM"] = qam_pending > 0
    submission["inReview"] = has_other_pending or (qam_pending > 0)
    return len(qam_states)


def _extract_version(name: str, prefix: str) -> str:
    """Extract version number from a package name string."""
    remainder = name.removeprefix(prefix)
    return next((part for part in remainder.split("-") if VERSION_EXTRACT_REGEX.search(part)), "")


@lru_cache(maxsize=512)
def get_product_version_from_repo_listing(project: str, product_name: str, repository: str) -> str:
    """Determine the product version by inspecting an OBS repository listing."""
    project_path = project.replace(":", ":/")
    url = f"{config.settings.obs_download_url}/{project_path}/{repository}/repo?jsontable"
    start = f"{product_name}-"
    try:
        r = retried_requests.get(url)
        r.raise_for_status()
        data = r.json()["data"]
    except requests.exceptions.HTTPError as e:
        log.warning("Repo ignored: Could not query repository '%s' (%s->%s): %s", repository, product_name, project, e)
        return ""
    # Catching both because requests' JSONDecodeError might not inherit from json's
    except (json.JSONDecodeError, requests.exceptions.JSONDecodeError) as e:
        log.info("Invalid JSON document at '%s', ignoring: %s", url, e)
        return ""
    except requests.exceptions.RequestException as e:
        log.warning("Product version unresolved: Could not read from '%s': %s", url, e)
        return ""
    versions = (_extract_version(entry["name"], start) for entry in data if entry["name"].startswith(start))
    return next((v for v in versions if len(v) > 0), "")


def add_channel_for_build_result(
    project: str,
    arch: str,
    product_name: str,
    res: Any,  # noqa: ANN401
    projects: set[str],
) -> str:
    """Construct a channel string for a build result and add it to the project set."""
    channel = f"{project}:{arch}"
    if arch == "local":
        return channel

    # read product version from scmsync element if possible, e.g. 15.99
    product_version = next(
        (
            pv
            for _, pv in (get_product_name_and_version_from_scmsync(e.text) for e in res.findall("scmsync"))
            if len(pv) > 0
        ),
        "",
    )

    # read product version from directory listing if the project is for a concrete product
    if (
        len(product_name) != 0
        and len(product_version) == 0
        and ("all" in config.settings.obs_products_set or product_name in config.settings.obs_products_set)
    ):
        product_version = get_product_version_from_repo_listing(project, product_name, res.get("repository"))

    # append product version to channel if known; otherwise skip channel if this is for a concrete product
    if len(product_version) > 0:
        channel = f"{channel}#{product_version}"
    elif len(product_name) > 0:
        log.debug("Channel skipped: Product version for build result %s:%s could not be determined", project, arch)
        return channel

    projects.add(channel)
    return channel


def add_build_result(
    submission: dict[str, Any],
    res: Any,  # noqa: ANN401
    results: BuildResults,
) -> None:
    """Process a single build result and update submission and results."""
    project = res.get("project")
    product = get_product_name(project)
    scm_key = f"scminfo_{product}" if product else "scminfo"
    for found in (e.text for e in res.findall("scminfo") if e.text):
        if (existing := submission.get(scm_key)) and found != existing:
            msg = "PR git:%s: Inconsistent SCM info for project %s: found '%s' vs '%s'"
            log.warning(msg, submission["number"], project, found, existing)
            continue
        submission[scm_key] = found
    channel = add_channel_for_build_result(project, res.get("arch"), product, res, results.projects)
    if "all" not in config.settings.obs_products_set and product not in config.settings.obs_products_set:
        return
    if res.get("state") != "published":
        results.unpublished.add(channel)
        return
    statuses = res.findall("status")
    results.successful.update(s.get("package") for s in statuses if s.get("code") == "succeeded")
    results.failed.update(s.get("package") for s in statuses if s.get("code") not in {"excluded", "succeeded"})


def get_multibuild_data(obs_project: str) -> str:
    """Fetch multibuild configuration data for an OBS project."""
    r = MultibuildFlavorResolver(config.settings.obs_url, obs_project, "000productcompose")
    return r.get_multibuild_data()


def determine_relevant_archs_from_multibuild_info(obs_project: str, *, dry: bool) -> set[str] | None:
    """Determine which architectures are relevant for a product based on multibuild data."""
    # retrieve the _multibuild info like `osc cat SUSE:SLFO:1.1.99:PullRequest:124:SLES 000productcompose _multibuild`
    product_name = get_product_name(obs_project)
    if not product_name:
        return None
    product_prefix = product_name.replace("SL-", "sle_").replace(":", "_").lower() + "_"
    prefix_len = len(product_prefix)
    if dry:
        multibuild_data = read_utf8("_multibuild-124-" + obs_project + ".xml")
    else:
        try:
            multibuild_data = get_multibuild_data(obs_project)
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            log.warning("Could not determine relevant architectures for %s: %s", obs_project, e)
            return None

    # determine from the flavors we got what architectures are actually expected to be present

    # note: The build info will contain result elements for archs like `local` and `ppc64le` that and the published
    # flag set even though no repos for those products are actually present. Considering these would lead to problems
    # later on (e.g. when computing the repohash) so it makes sense to reduce the archs we are considering to actually
    # relevant ones.
    flavors = MultibuildFlavorResolver.parse_multibuild_data(multibuild_data)
    relevant_archs = {
        flavor[prefix_len:] for flavor in flavors if flavor.startswith(product_prefix) and flavor[prefix_len:] in ARCHS
    }
    log.debug("Relevant archs for %s: %s", obs_project, sorted(relevant_archs))
    return relevant_archs


def is_build_result_relevant(res: Any, relevant_archs: set[str] | None) -> bool:  # noqa: ANN401
    """Check if a build result is relevant for the current product and architecture."""
    if config.settings.obs_repo_type and res.get("repository") != config.settings.obs_repo_type:
        return False
    arch = res.get("arch")
    return arch == "local" or relevant_archs is None or arch in relevant_archs


def _get_project_results(obs_project: str, *, dry: bool, results: BuildResults) -> list[Any]:
    """Fetch build results for an OBS project."""
    build_info_url = osc.core.makeurl(config.settings.obs_url, ["build", obs_project, "_result"])
    if dry:
        return read_xml("build-results-124-" + obs_project).getroot().findall("result")
    try:
        return osc.util.xml.xml_parse(http_GET(build_info_url)).getroot().findall("result")
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

    submission.update({
        "failed_or_unpublished_packages": sorted(results.failed | results.unpublished | results.unavailable),
        "successful_packages": sorted(results.successful),
    })

    if "channels" not in submission:
        submission["channels"] = []

    for result in sorted(results.projects):
        if result not in submission["channels"]:
            submission["channels"].append(result)

    if (
        "scminfo" not in submission
        and len(config.settings.obs_products_set) == 1
        and "all" not in config.settings.obs_products_set
    ):
        submission["scminfo"] = submission.get("scminfo_" + next(iter(config.settings.obs_products_set)), "")


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
            response = retried_requests.get(patch_info_url, verify=False, headers=token)
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


def make_submission_from_gitea_pr(
    pr: dict[str, Any],
    token: dict[str, str],
    *,
    only_successful_builds: bool,
    only_requested_prs: bool,
    dry: bool,
) -> dict[str, Any] | None:
    """Create a dashboard-compatible submission record from a Gitea PR."""
    log.debug("Fetching info for PR git:%s from Gitea", pr.get("number", "?"))
    try:
        number = pr["number"]
        repo = pr["base"]["repo"]
        repo_name = repo["full_name"]
        submission = {
            "number": number,
            "project": repo["name"],
            # "Emergency Maintenance Update", a flag used to raise a priority in scheduler
            # see openqabot/types/incidents.py#L227
            "emu": False,
            "isActive": pr["state"] == "open",
            "inReviewQAM": False,
            "inReview": False,
            "approved": False,
            # `_patchinfo` should contain something like <embargo_date>2025-05-01</embargo_date> if embargo applies
            "embargoed": False,
            "priority": 0,  # only used for display purposes on the dashboard, maybe read from a label at some point
            "rr_number": None,
            "packages": [],
            "channels": [],
            "url": pr["url"],
            "type": "git",
        }
        if dry:
            if number == 124:  # noqa: PLR2004
                reviews = read_json("reviews-124")
                comments = read_json("comments-124")
                files = read_json("files-124")
            else:
                reviews = []
                comments = []
                files = []
        else:
            reviews = get_json(reviews_url(repo_name, number), token)
            comments = get_json(comments_url(repo_name, number), token)
            files = get_json(changed_files_url(repo_name, number), token)
        if add_reviews(submission, reviews) < 1 and only_requested_prs:
            log.info("PR git:%s skipped: No reviews by %s", number, config.settings.obs_group)
            return None
        add_comments_and_referenced_build_results(submission, comments, dry=dry)
        if not submission["channels"]:
            log.info("PR git:%s skipped: No channels found", number)
            return None
        if only_successful_builds and not is_build_acceptable_and_log_if_not(submission, number):
            return None
        add_packages_from_files(submission, token, files, dry=dry)
        if not submission["packages"]:
            log.info("PR git:%s skipped: No packages found", number)
            return None

    except Exception:
        log.exception("Gitea API error: Unable to process PR git:%s", pr.get("number", "?"))
        return None
    return submission


def get_submissions_from_open_prs(
    open_prs: list[dict[str, Any]],
    token: dict[str, str],
    *,
    only_successful_builds: bool,
    only_requested_prs: bool,
    dry: bool,
) -> list[dict[str, Any]]:
    """Convert a list of open Gitea PRs into dashboard submissions."""
    submissions = []

    # configure osc to be able to request build info from OBS
    osc.conf.get_config(override_apiurl=config.settings.obs_url)

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
