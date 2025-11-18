# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import re
import urllib.error
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
from lxml import etree
from osc.core import MultibuildFlavorResolver

from openqabot import GIT_REVIEW_BOT, GITEA, OBS_DOWNLOAD_URL, OBS_GROUP, OBS_PRODUCTS, OBS_REPO_TYPE, OBS_URL
from openqabot.utils import retry10 as retried_requests

if TYPE_CHECKING:
    from openqabot.types import Repos

log = getLogger("bot.loader.gitea")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def make_token_header(token: str) -> dict[str, str]:
    return {} if token is None else {"Authorization": "token " + token}


def get_json(query: str, token: dict[str, str], host: str = GITEA) -> Any:
    return retried_requests.get(host + "/api/v1/" + query, verify=False, headers=token).json()


def post_json(query: str, token: dict[str, str], post_data: Any, host: str = GITEA) -> Any:
    url = host + "/api/v1/" + query
    res = retried_requests.post(url, verify=False, headers=token, json=post_data)
    if not res.ok:
        log.error("Unable to POST %s: %s", url, res.text)


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
    product_match = re.search(r".*:PullRequest:\d+:(.*)", obs_project)
    return product_match.group(1) if product_match else ""


def get_product_name_and_version_from_scmsync(scmsync_url: str) -> tuple[str, str]:
    m = re.search(r".*/products/(.*)#([\d\.]{2,6})$", scmsync_url)
    return (m.group(1), m.group(2)) if m else ("", "")


def compute_repo_url(
    base: str,
    product_name: str,
    repo: tuple[str, str, str],
    arch: str,
    path: str = "repodata/repomd.xml",
) -> str:
    # return codestream repo if product name is empty
    if product_name == "":
        # assing something like `http://download.suse.de/ibs/SUSE:/SLFO:/1.1.99:/PullRequest:/166/standard/repodata/repomd.xml`
        return f"{base}/{repo[0].replace(':', ':/')}:/{repo[1].replace(':', ':/')}/{OBS_REPO_TYPE}/{path}"

    # return product repo for specified product
    # assing something like `https://download.suse.de/ibs/SUSE:/SLFO:/1.1.99:/PullRequest:/166:/SLES/product/repo/SLES-15.99-x86_64/repodata/repomd.xml`
    return f"{base}/{repo[0].replace(':', ':/')}:/{repo[1].replace(':', ':/')}/{OBS_REPO_TYPE}/repo/{product_name}-{repo[2]}-{arch}/{path}"


def compute_repo_url_for_job_setting(
    base: str,
    repo: Repos,
    product_repo: list[str] | str | None,
    product_version: str | None,
) -> str:
    product_names = get_product_name(repo.version) if product_repo is None else product_repo
    product_version = repo.product_version if product_version is None else product_version
    return ",".join(
        (
            compute_repo_url(
                base,
                p,
                (repo.product, repo.version, product_version),
                repo.arch,
                "",
            )
            for p in (product_names if isinstance(product_names, list) else [product_names])
        ),
    )


def get_open_prs(token: dict[str, str], repo: str, *, dry: bool, number: int | None) -> list[Any]:
    if dry:
        return read_json("pulls")
    open_prs = []
    page = 1
    if number is not None:
        pr = get_json(f"repos/{repo}/pulls/{number}", token)
        log.debug("PR %i: %s", number, pr)
        open_prs.append(pr)
        return open_prs
    while True:
        # https://docs.gitea.com/api/1.20/#tag/repository/operation/repolistPullRequests
        prs_on_page = get_json(f"repos/{repo}/pulls?state=open&page={page}", token)
        if not isinstance(prs_on_page, list) or len(prs_on_page) <= 0:
            break
        open_prs.extend(prs_on_page)
        page += 1
    return open_prs


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


def is_review_requested_by(review: dict[str, Any], users: list[str]) -> bool:
    user_specifications = (
        get_name(review, "user", "login"),  # review via our bot account or review bot
        get_name(review, "team", "name"),  # review request for team bot is part of
    )
    return any(user in user_specifications for user in users)


def add_reviews(incident: dict[str, Any], reviews: list[Any]) -> int:
    approvals = 0
    changes_requested = 0
    review_requested = 0
    pending = 0
    pending_qam = 0
    reviews_by_qam = 0
    for review in reviews:
        # ignore dismissed reviews
        if review.get("dismissed", True):
            continue
        # accumulate number of reviews per state
        state = review.get("state", "")
        if is_review_requested_by(review, [OBS_GROUP, GIT_REVIEW_BOT]):
            reviews_by_qam += 1
            if state == "APPROVED":
                approvals += 1
            elif state == "PENDING":
                pending_qam += 1
            elif state == "REQUEST_CHANGES":
                changes_requested += 1
            elif state == "REQUEST_REVIEW":
                pending_qam += 1
                review_requested += 1
        elif state in {"PENDING", "REQUEST_REVIEW"}:
            pending += 1
    incident["approved"] = approvals > 0 and changes_requested + review_requested == 0
    incident["inReview"] = pending + pending_qam > 0
    incident["inReviewQAM"] = pending_qam > 0
    return reviews_by_qam


@lru_cache(maxsize=512)
def get_product_version_from_repo_listing(project: str, product_name: str, repository: str) -> str:
    project_path = project.replace(":", ":/")
    url = f"{OBS_DOWNLOAD_URL}/{project_path}/{repository}/repo?jsontable"
    start = f"{product_name}-"
    version = ""
    try:
        for entry in retried_requests.get(url).json()["data"]:
            name = entry["name"]
            if not name.startswith(start):
                continue
            parts = filter(lambda x: re.search(r"[.\d]+", x), name[len(start) :].split("-"))
            version = next(parts, "")
            if len(version) > 0:
                return version
    except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
        log.warning("Unable to read product version from '%s': %s", url, e)
    return version


def add_channel_for_build_result(
    project: str,
    arch: str,
    product_name: str,
    res: Any,
    projects: set[str],
) -> tuple[str, bool]:
    channel = f"{project}:{arch}"
    if arch == "local":
        return channel

    # read product version from scmsync element if possible, e.g. 15.99
    product_version = ""
    for scmsync_element in res.findall("scmsync"):
        (_, product_version) = get_product_name_and_version_from_scmsync(scmsync_element.text)
        if len(product_version) > 0:
            break

    # read product version from directory listing if the project is for a concrete product
    if len(product_name) != 0 and len(product_version) == 0 and product_name in OBS_PRODUCTS:
        product_version = get_product_version_from_repo_listing(project, product_name, res.get("repository"))

    # append product version to channel if known; otherwise skip channel if this is for a concrete product
    if len(product_version) > 0:
        channel = f"{channel}#{product_version}"
    elif len(product_name) > 0:
        log.warning("Unable to determine product version for build result %s:%s, not adding channel", project, arch)
        return channel

    projects.add(channel)
    return channel


def add_build_result(  # noqa: PLR0917 too-many-positional-arguments
    incident: dict[str, Any],
    res: Any,
    projects: set[str],
    successful_packages: set[str],
    unpublished_repos: set[str],
    failed_packages: set[str],
) -> None:
    state = res.get("state")
    project = res.get("project")
    product_name = get_product_name(project)
    arch = res.get("arch")
    # read Git hash from scminfo element
    scm_info_key = "scminfo_" + product_name if len(product_name) != 0 else "scminfo"
    for scminfo_element in res.findall("scminfo"):
        found_scminfo = scminfo_element.text
        existing_scminfo = incident.get(scm_info_key)
        if len(found_scminfo) > 0:
            if existing_scminfo is None or found_scminfo == existing_scminfo:
                incident[scm_info_key] = found_scminfo
            else:
                log.warning(
                    "Found inconsistent scminfo for PR %i and project %s, found '%s' and previously got '%s'",
                    incident["number"],
                    project,
                    found_scminfo,
                    existing_scminfo,
                )
    # add channel for this build result
    channel = add_channel_for_build_result(project, arch, product_name, res, projects)
    if product_name not in OBS_PRODUCTS:
        return
    # require only relevant projects to be built/published
    if state != "published":
        unpublished_repos.add(channel)
        return
    for status in res.findall("status"):
        code = status.get("code")
        if code == "excluded":
            continue
        if code == "succeeded":
            successful_packages.add(status.get("package"))
        else:
            failed_packages.add(status.get("package"))


def get_multibuild_data(obs_project: str) -> str:
    r = MultibuildFlavorResolver(OBS_URL, obs_project, "000productcompose")
    return r.get_multibuild_data()


def determine_relevant_archs_from_multibuild_info(obs_project: str, *, dry: bool) -> set[str]:
    # retrieve the _multibuild info like `osc cat SUSE:SLFO:1.1.99:PullRequest:124:SLES 000productcompose _multibuild`
    product_name = get_product_name(obs_project)
    if product_name == "":
        return None
    product_prefix = product_name.replace(":", "_").lower() + "_"
    prefix_len = len(product_prefix)
    if dry:
        multibuild_data = read_utf8("_multibuild-124-" + obs_project + ".xml")
    else:
        try:
            multibuild_data = get_multibuild_data(obs_project)
        except Exception as e:  # noqa: BLE001 true-positive: Consider to use fine-grained exceptions
            log.warning("Unable to determine relevant archs for %s: %s", obs_project, e)
            return None

    # determine from the flavors we got what architectures are actually expected to be present
    # note: The build info will contain result elements for archs like `local` and `ppc64le` that and the published
    #       flag set even though no repos for those products are actually present. Considering these would lead to
    #       problems later on (e.g. when computing the repohash) so it makes sense to reduce the archs we are considering
    #       to actually relevant ones.
    flavors = MultibuildFlavorResolver.parse_multibuild_data(multibuild_data)
    relevant_archs = set()
    for flavor in flavors:
        if flavor.startswith(product_prefix):
            arch = flavor[prefix_len:]
            if arch in {"x86_64", "aarch64", "ppc64le", "s390x"}:
                relevant_archs.add(arch)
    log.debug("Relevant archs for %s: %s", obs_project, sorted(relevant_archs))
    return relevant_archs


def is_build_result_relevant(res: Any, relevant_archs: set[str]) -> bool:
    if OBS_REPO_TYPE and res.get("repository") != OBS_REPO_TYPE:
        return False
    arch = res.get("arch")
    return arch == "local" or relevant_archs is None or arch in relevant_archs


def add_build_results(incident: dict[str, Any], obs_urls: list[str], *, dry: bool) -> None:
    successful_packages = set()
    unavailable_projects = set()
    unpublished_repos = set()
    failed_packages = set()
    projects = set()
    for url in obs_urls:
        project_match = re.search(r".*/project/show/(.*)", url)
        if project_match:
            obs_project = project_match.group(1)
            log.debug("Checking OBS project %s", obs_project)
            relevant_archs = determine_relevant_archs_from_multibuild_info(obs_project, dry=dry)
            build_info_url = osc.core.makeurl(OBS_URL, ["build", obs_project, "_result"])
            if dry:
                build_info = read_xml("build-results-124-" + obs_project)
            else:
                try:
                    build_info = osc.util.xml.xml_parse(osc.core.http_GET(build_info_url))
                except urllib.error.HTTPError:
                    unavailable_projects.add(obs_project)
                    log.exception("Unable to read build results of project %s", build_info_url)
                    continue
            for res in build_info.getroot().findall("result"):
                if not is_build_result_relevant(res, relevant_archs):
                    continue
                add_build_result(
                    incident,
                    res,
                    projects,
                    successful_packages,
                    unpublished_repos,
                    failed_packages,
                )
    if len(unpublished_repos) > 0:
        log.info(
            "Some repos for PR %i have not been published yet: %s",
            incident["number"],
            ", ".join(unpublished_repos),
        )
    if len(failed_packages) > 0:
        log.info(
            "Some packages for PR %i have failed: %s",
            incident["number"],
            ", ".join(failed_packages),
        )
    incident["channels"] = [*projects]
    incident["failed_or_unpublished_packages"] = [*failed_packages, *unpublished_repos, *unavailable_projects]
    incident["successful_packages"] = [*successful_packages]
    if "scminfo" not in incident and len(OBS_PRODUCTS) == 1:
        incident["scminfo"] = incident.get("scminfo_" + next(iter(OBS_PRODUCTS)), "")


def add_comments_and_referenced_build_results(
    incident: dict[str, Any],
    comments: list[Any],
    *,
    dry: bool,
) -> None:
    for comment in reversed(comments):
        body = comment["body"]
        user_name = comment["user"]["username"]
        if user_name == "autogits_obs_staging_bot":
            add_build_results(incident, re.findall(r"https://[^ ]*", body), dry=dry)
            break


def add_packages_from_patchinfo(
    incident: dict[str, Any],
    token: dict[str, str],
    patch_info_url: str,
    *,
    dry: bool,
) -> None:
    if dry:
        patch_info = read_xml("patch-info")
    else:
        patch_info = osc.util.xml.xml_fromstring(retried_requests.get(patch_info_url, verify=False, headers=token).text)
    for res in patch_info.findall("package"):
        incident["packages"].append(res.text)


def add_packages_from_files(incident: dict[str, Any], token: dict[str, str], files: list[Any], *, dry: bool) -> None:
    for file_info in files:
        file_name = file_info.get("filename", "").split("/")[-1]
        raw_url = file_info.get("raw_url")
        if file_name == "_patchinfo" and raw_url is not None:
            add_packages_from_patchinfo(incident, token, raw_url, dry=dry)


def is_build_acceptable_and_log_if_not(incident: dict[str, Any], number: int) -> bool:
    failed_or_unpublished_packages = len(incident["failed_or_unpublished_packages"])
    if failed_or_unpublished_packages > 0:
        log.info("Skipping PR %i, not all packages succeeded and published", number)
        return False
    if len(incident["successful_packages"]) < 1:
        info = "Skipping PR %i, no packages have been built/published (there are %i failed/unpublished packages)"
        log.info(info, number, failed_or_unpublished_packages)
        return False
    return True


def make_incident_from_pr(
    pr: dict[str, Any],
    token: dict[str, str],
    *,
    only_successful_builds: bool,
    only_requested_prs: bool,
    dry: bool,
) -> dict[str, Any] | None:
    log.info("Getting info about PR %s from Gitea", pr.get("number", "?"))
    try:
        number = pr["number"]
        repo = pr["base"]["repo"]
        repo_name = repo["full_name"]
        incident = {
            "number": number,
            "project": repo["name"],
            "emu": False,  # "Emergency Maintenance Update", a flag used to raise a priority in scheduler, see openqabot/types/incidents.py#L227
            "isActive": pr["state"] == "open",
            "inReviewQAM": False,
            "inReview": False,
            "approved": False,
            "embargoed": False,  # `_patchinfo` should contain something like <embargo_date>2025-05-01</embargo_date> if embargo applies
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
        if add_reviews(incident, reviews) < 1 and only_requested_prs:
            log.info("Skipping PR %s, no reviews by %s", number, OBS_GROUP)
            return None
        add_comments_and_referenced_build_results(incident, comments, dry=dry)
        if len(incident["channels"]) == 0:
            log.info("Skipping PR %s, no channels found/considered", number)
            return None
        if only_successful_builds and not is_build_acceptable_and_log_if_not(incident, number):
            return None
        add_packages_from_files(incident, token, files, dry=dry)
        if len(incident["packages"]) == 0:
            log.info("Skipping PR %s, no packages found/considered", number)
            return None

    except Exception:  # pylint: disable=broad-except
        log.exception("Unable to process PR %s", pr.get("number", "?"))
        return None
    return incident


def get_incidents_from_open_prs(
    open_prs: list[dict[str, Any]],
    token: dict[str, str],
    *,
    only_successful_builds: bool,
    only_requested_prs: bool,
    dry: bool,
) -> list[dict[str, Any]]:
    incidents = []

    # configure osc to be able to request build info from OBS
    osc.conf.get_config(override_apiurl=OBS_URL)

    with futures.ThreadPoolExecutor() as executor:
        future_inc = [
            executor.submit(
                make_incident_from_pr,
                pr,
                token,
                only_successful_builds=only_successful_builds,
                only_requested_prs=only_requested_prs,
                dry=dry,
            )
            for pr in open_prs
        ]
        incidents = (future.result() for future in futures.as_completed(future_inc))
        return [inc for inc in incidents if inc]
