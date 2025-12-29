# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import re
import urllib.error
from collections import Counter
from concurrent import futures
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

from openqabot.config import GIT_REVIEW_BOT, GITEA, OBS_DOWNLOAD_URL, OBS_GROUP, OBS_PRODUCTS, OBS_REPO_TYPE, OBS_URL
from openqabot.utils import retry10 as retried_requests

if TYPE_CHECKING:
    from openqabot.types.types import Repos

ARCHS = {"x86_64", "aarch64", "ppc64le", "s390x"}

log = getLogger("bot.loader.gitea")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PROJECT_PRODUCT_REGEX = re.compile(r".*:PullRequest:\d+:(.*)")
SCMSYNC_REGEX = re.compile(r".*/products/(.*)#([\d\.]{2,6})$")
VERSION_EXTRACT_REGEX = re.compile(r"[.\d]+")
OBS_PROJECT_SHOW_REGEX = re.compile(r".*/project/show/(.*)")
URL_FINDALL_REGEX = re.compile(r"https://[^ \n]*")


def make_token_header(token: str) -> dict[str, str]:
    return {} if token is None else {"Authorization": "token " + token}


def get_json(query: str, token: dict[str, str], host: str = GITEA) -> Any:
    return retried_requests.get(host + "/api/v1/" + query, verify=False, headers=token).json()


def post_json(query: str, token: dict[str, str], post_data: Any, host: str = GITEA) -> Any:
    url = host + "/api/v1/" + query
    res = retried_requests.post(url, verify=False, headers=token, json=post_data)
    if not res.ok:
        log.error("Gitea API error: POST to %s failed: %s", url, res.text)


def read_utf8(name: str) -> str:
    return Path(f"responses/{name}").read_text(encoding="utf8")


def read_json(name: str) -> Any:
    return json.loads(Path(f"responses/{name}.json").read_text(encoding="utf8"))


def read_xml(name: str) -> etree.ElementTree:
    return etree.parse(f"responses/{name}.xml")


def reviews_url(repo_name: str, number: int) -> str:
    # https://docs.gitea.com/api/1.20/#tag/repository/operation/repolistPullReviews
    return f"repos/{repo_name}/pulls/{number}/reviews"


def changed_files_url(repo_name: str, number: int) -> str:
    # https://docs.gitea.com/api/1.20/#tag/repository/operation/repoGetPullRequestFiles
    return f"repos/{repo_name}/pulls/{number}/files"


def comments_url(repo_name: str, number: int) -> str:
    # https://docs.gitea.com/api/1.20/#tag/issue/operation/issueCreateComment
    return f"repos/{repo_name}/issues/{number}/comments"


def get_product_name(obs_project: str) -> str:
    product_match = PROJECT_PRODUCT_REGEX.search(obs_project)
    return product_match.group(1) if product_match else ""


def get_product_name_and_version_from_scmsync(scmsync_url: str) -> tuple[str, str]:
    m = SCMSYNC_REGEX.search(scmsync_url)
    return (m.group(1), m.group(2)) if m else ("", "")


def compute_repo_url(
    base: str,
    product_name: str,
    repo: tuple[str, ...],
    arch: str,
    path: str = "repodata/repomd.xml",
) -> str:
    # return codestream repo if product name is empty
    start = f"{base}/{repo[0].replace(':', ':/')}:/{repo[1].replace(':', ':/')}/{OBS_REPO_TYPE}"
    # for empty product assign something like `http://download.suse.de/ibs/SUSE:/SLFO:/1.1.99:/PullRequest:/166/standard/repodata/repomd.xml`
    # otherwise return product repo for specified product
    # assing something like `https://download.suse.de/ibs/SUSE:/SLFO:/1.1.99:/PullRequest:/166:/SLES/product/repo/SLES-15.99-x86_64/repodata/repomd.xml`
    if product_name == "":
        return f"{start}/{path}"

    msg = f"Product version must be provided for {product_name}"
    assert len(repo) > 2, msg
    assert repo[2], msg
    product_version = repo[2]
    return f"{start}/repo/{product_name}-{product_version}-{arch}/{path}"


def compute_repo_url_for_job_setting(
    base: str,
    repo: Repos,
    product_repo: list[str] | str | None,
    product_version: str | None,
) -> str:
    product_names = get_product_name(repo.version) if product_repo is None else product_repo
    product_version = repo.product_version if product_version is None else product_version
    product_list = product_names if isinstance(product_names, list) else [product_names]
    repo_tuple = (repo.product, repo.version, product_version)
    return ",".join(compute_repo_url(base, p, repo_tuple, repo.arch, "") for p in product_list)


def get_open_prs(token: dict[str, str], repo: str, *, dry: bool, number: int | None) -> list[Any]:
    log.debug("Fetching open PRs from '%s'%s", repo, ", dry-run" if dry else "")
    if dry:
        return read_json("pulls")
    if number is not None:
        try:
            pr = get_json(f"repos/{repo}/pulls/{number}", token)
        except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError):
            log.exception("PR #%s ignored: Could not read PR metadata", number)
            return []
        log.debug("PR %i: %s", number, pr)
        return [pr]

    def iter_pr_pages() -> Any:
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


def review_pr(
    token: dict[str, str],
    repo_name: str,
    pr_number: int,
    msg: str,
    commit_id: str,
    *,
    approve: bool = True,
) -> None:
    if GIT_REVIEW_BOT:
        review_url = comments_url(repo_name, pr_number)
        review_cmd = f"@{GIT_REVIEW_BOT}: "
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
    entity = review.get(of)
    return entity.get(via, "") if entity is not None else ""


def is_review_requested_by(review: dict[str, Any], users: tuple[str, ...] = (OBS_GROUP, GIT_REVIEW_BOT)) -> bool:
    user_specifications = (
        get_name(review, "user", "login"),  # review via our bot account or review bot
        get_name(review, "team", "name"),  # review request for team bot is part of
    )
    return any(user in user_specifications for user in users)


def add_reviews(submission: dict[str, Any], reviews: list[Any]) -> int:
    PENDING_STATES = {"PENDING", "REQUEST_REVIEW"}
    open_reviews = [r for r in reviews if not r.get("dismissed", True)]
    qam_states = [r.get("state", "") for r in open_reviews if is_review_requested_by(r)]
    has_other_pending = any(r.get("state", "") in PENDING_STATES for r in open_reviews if not is_review_requested_by(r))
    counts = Counter(qam_states)
    qam_pending = counts["PENDING"] + counts["REQUEST_REVIEW"]
    qam_blocking = counts["REQUEST_CHANGES"] + counts["REQUEST_REVIEW"]
    submission["approved"] = (counts["APPROVED"] > 0) and (qam_blocking == 0)
    submission["inReviewQAM"] = qam_pending > 0
    submission["inReview"] = has_other_pending or (qam_pending > 0)
    return len(qam_states)


def _extract_version(name: str, prefix: str) -> str:
    remainder = name.removeprefix(prefix)
    return next((part for part in remainder.split("-") if VERSION_EXTRACT_REGEX.search(part)), "")


@lru_cache(maxsize=512)
def get_product_version_from_repo_listing(project: str, product_name: str, repository: str) -> str:
    project_path = project.replace(":", ":/")
    url = f"{OBS_DOWNLOAD_URL}/{project_path}/{repository}/repo?jsontable"
    start = f"{product_name}-"
    try:
        r = retried_requests.get(url)
        r.raise_for_status()
        data = r.json()["data"]
    except requests.exceptions.HTTPError as e:
        log.warning("Repo ignored: Could not query repository '%s' (%s->%s): %s", repository, product_name, project, e)
        return ""
    except requests.exceptions.RequestException as e:
        log.warning("Product version unresolved: Could not read from '%s': %s", url, e)
        return ""
    except (json.JSONDecodeError, requests.exceptions.JSONDecodeError) as e:
        log.info("Invalid JSON document at '%s', ignoring: %s", url, e)
        return ""
    versions = (_extract_version(entry["name"], start) for entry in data if entry["name"].startswith(start))
    return next((v for v in versions if len(v) > 0), "")


def add_channel_for_build_result(
    project: str,
    arch: str,
    product_name: str,
    res: Any,
    projects: set[str],
) -> str:
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
    if len(product_name) != 0 and len(product_version) == 0 and product_name in OBS_PRODUCTS:
        product_version = get_product_version_from_repo_listing(project, product_name, res.get("repository"))

    # append product version to channel if known; otherwise skip channel if this is for a concrete product
    if len(product_version) > 0:
        channel = f"{channel}#{product_version}"
    elif len(product_name) > 0:
        log.debug("Channel skipped: Product version for build result %s:%s could not be determined", project, arch)
        return channel

    projects.add(channel)
    return channel


def add_build_result(  # noqa: PLR0917 too-many-positional-arguments
    submission: dict[str, Any],
    res: Any,
    projects: set[str],
    successful_packages: set[str],
    unpublished_repos: set[str],
    failed_packages: set[str],
) -> None:
    project = res.get("project")
    product = get_product_name(project)
    scm_key = f"scminfo_{product}" if product else "scminfo"
    for found in (e.text for e in res.findall("scminfo") if e.text):
        if (existing := submission.get(scm_key)) and found != existing:
            msg = "PR %s: Inconsistent SCM info for project %s: found '%s' vs '%s'"
            log.warning(msg, submission["number"], project, found, existing)
            continue
        submission[scm_key] = found
    channel = add_channel_for_build_result(project, res.get("arch"), product, res, projects)
    if product not in OBS_PRODUCTS:
        return
    if res.get("state") != "published":
        unpublished_repos.add(channel)
        return
    statuses = res.findall("status")
    successful_packages.update(s.get("package") for s in statuses if s.get("code") == "succeeded")
    failed_packages.update(s.get("package") for s in statuses if s.get("code") not in {"excluded", "succeeded"})


def get_multibuild_data(obs_project: str) -> str:
    r = MultibuildFlavorResolver(OBS_URL, obs_project, "000productcompose")
    return r.get_multibuild_data()


def determine_relevant_archs_from_multibuild_info(obs_project: str, *, dry: bool) -> set[str] | None:
    # retrieve the _multibuild info like `osc cat SUSE:SLFO:1.1.99:PullRequest:124:SLES 000productcompose _multibuild`
    product_name = get_product_name(obs_project)
    if product_name == "":
        return None
    product_prefix = product_name.replace("SL-", "sle_").replace(":", "_").lower() + "_"
    prefix_len = len(product_prefix)
    if dry:
        multibuild_data = read_utf8("_multibuild-124-" + obs_project + ".xml")
    else:
        try:
            multibuild_data = get_multibuild_data(obs_project)
        except Exception as e:  # noqa: BLE001 true-positive: Consider to use fine-grained exceptions
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


def is_build_result_relevant(res: Any, relevant_archs: set[str] | None) -> bool:
    if OBS_REPO_TYPE and res.get("repository") != OBS_REPO_TYPE:
        return False
    arch = res.get("arch")
    return arch == "local" or relevant_archs is None or arch in relevant_archs


def _get_project_results(obs_project: str, *, dry: bool, unavailable_projects: set[str]) -> list[Any]:
    build_info_url = osc.core.makeurl(OBS_URL, ["build", obs_project, "_result"])
    if dry:
        return read_xml("build-results-124-" + obs_project).getroot().findall("result")
    try:
        return osc.util.xml.xml_parse(http_GET(build_info_url)).getroot().findall("result")
    except urllib.error.HTTPError:
        unavailable_projects.add(obs_project)
        log.info("Build results for project %s unreadable, skipping: %s", obs_project, build_info_url)
        return []


def _process_obs_url(
    url: str,
    submission: dict[str, Any],
    *,
    dry: bool,
    results: dict[str, set[str]],
) -> None:
    if not (project_match := OBS_PROJECT_SHOW_REGEX.search(url)):
        return
    obs_project = project_match.group(1)
    log.debug("Checking OBS project %s", obs_project)
    relevant_archs = determine_relevant_archs_from_multibuild_info(obs_project, dry=dry)

    for res in _get_project_results(obs_project, dry=dry, unavailable_projects=results["unavailable"]):
        if is_build_result_relevant(res, relevant_archs):
            add_build_result(
                submission,
                res,
                results["projects"],
                results["successful"],
                results["unpublished"],
                results["failed"],
            )


def add_build_results(submission: dict[str, Any], obs_urls: list[str], *, dry: bool) -> None:
    results = {
        "successful": set(),
        "unavailable": set(),
        "unpublished": set(),
        "failed": set(),
        "projects": set(),
    }

    for url in obs_urls:
        _process_obs_url(url, submission, dry=dry, results=results)

    if results["unpublished"]:
        log.info("PR %i: Some repos not published yet: %s", submission["number"], ", ".join(results["unpublished"]))
    if results["failed"]:
        log.info("PR %i: Some packages failed: %s", submission["number"], ", ".join(results["failed"]))

    submission.update({
        "channels": sorted(results["projects"]),
        "failed_or_unpublished_packages": sorted(results["failed"] | results["unpublished"] | results["unavailable"]),
        "successful_packages": sorted(results["successful"]),
    })

    if "scminfo" not in submission and len(OBS_PRODUCTS) == 1:
        submission["scminfo"] = submission.get("scminfo_" + next(iter(OBS_PRODUCTS)), "")


def add_comments_and_referenced_build_results(
    submission: dict[str, Any],
    comments: list[Any],
    *,
    dry: bool,
) -> None:
    bot_comment = next(
        (comment for comment in reversed(comments) if comment["user"]["username"] == "autogits_obs_staging_bot"),
        None,
    )
    if bot_comment:
        add_build_results(submission, URL_FINDALL_REGEX.findall(bot_comment["body"]), dry=dry)


def add_packages_from_patchinfo(
    submission: dict[str, Any],
    token: dict[str, str],
    patch_info_url: str,
    *,
    dry: bool,
) -> None:
    if dry:
        patch_info = read_xml("patch-info")
    else:
        patch_info = osc.util.xml.xml_fromstring(retried_requests.get(patch_info_url, verify=False, headers=token).text)
    submission["packages"].extend(res.text for res in patch_info.findall("package"))


def add_packages_from_files(submission: dict[str, Any], token: dict[str, str], files: list[Any], *, dry: bool) -> None:
    for file_info in files:
        file_name = file_info.get("filename", "").split("/")[-1]
        raw_url = file_info.get("raw_url")
        if file_name == "_patchinfo" and raw_url is not None:
            add_packages_from_patchinfo(submission, token, raw_url, dry=dry)


def is_build_acceptable_and_log_if_not(submission: dict[str, Any], number: int) -> bool:
    failed_or_unpublished_packages = len(submission["failed_or_unpublished_packages"])
    if failed_or_unpublished_packages > 0:
        log.info("Skipping PR %i: Not all packages succeeded or published", number)
        return False
    if len(submission["successful_packages"]) < 1:
        info = "Skipping PR %i: No packages have been built/published (there are %i failed/unpublished packages)"
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
    log.debug("Fetching info for PR %s from Gitea", pr.get("number", "?"))
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
            if number == 124:
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
            log.info("PR %s skipped: No reviews by %s", number, OBS_GROUP)
            return None
        add_comments_and_referenced_build_results(submission, comments, dry=dry)
        if not submission["channels"]:
            log.info("PR %s skipped: No channels found", number)
            return None
        if only_successful_builds and not is_build_acceptable_and_log_if_not(submission, number):
            return None
        add_packages_from_files(submission, token, files, dry=dry)
        if not submission["packages"]:
            log.info("PR %s skipped: No packages found", number)
            return None

    except Exception:
        log.exception("Gitea API error: Unable to process PR %s", pr.get("number", "?"))
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
    submissions = []

    # configure osc to be able to request build info from OBS
    osc.conf.get_config(override_apiurl=OBS_URL)

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
