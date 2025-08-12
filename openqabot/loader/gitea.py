# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import concurrent.futures as CT
from logging import getLogger
from typing import Any, List, Set, Dict, Tuple
import re
import xml.etree.ElementTree as ET

import json
import urllib3
import urllib3.exceptions

from osc.core import MultibuildFlavorResolver
import osc.conf
import osc.core
import osc.util.xml

from ..utils import retry10 as requests
from .. import GITEA, OBS_GROUP, OBS_URL, OBS_REPO_TYPE, OBS_PRODUCTS
from ..types import Repos

log = getLogger("bot.loader.gitea")

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def make_token_header(token: str) -> Dict[str, str]:
    return {} if token is None else {"Authorization": "token " + token}


def get_json(query: str, token: Dict[str, str], host: str = GITEA) -> Any:
    try:
        return requests.get(
            host + "/api/v1/" + query, verify=False, headers=token
        ).json()
    except Exception as e:
        log.exception(e)
        raise e


def post_json(
    query: str, token: Dict[str, str], post_data: Any, host: str = GITEA
) -> Any:
    try:
        url = host + "/api/v1/" + query
        res = requests.post(url, verify=False, headers=token, data=post_data)
        if not res.ok:
            log.error("Unable to POST %s: %s", url, res.text)
    except Exception as e:
        log.exception(e)
        raise e


def read_utf8(name: str) -> Any:
    with open("responses/%s" % name, "r", encoding="utf8") as utf8:
        return utf8.read()


def read_json(name: str) -> Any:
    with open("responses/%s.json" % name, "r", encoding="utf8") as json_file:
        return json.loads(json_file.read())


def read_xml(name: str) -> Any:
    return ET.parse("responses/%s.xml" % name)


def reviews_url(repo_name: str, number: int):
    # https://docs.gitea.com/api/1.20/#tag/repository/operation/repoListPullReviews
    return "repos/%s/pulls/%s/reviews" % (repo_name, number)


def changed_files_url(repo_name: str, number: int):
    # https://docs.gitea.com/api/1.20/#tag/repository/operation/repoGetPullRequestFiles
    return "repos/%s/pulls/%s/files" % (repo_name, number)


def comments_url(repo_name: str, number: int):
    # https://docs.gitea.com/api/1.20/#tag/issue/operation/issueRemoveIssueBlocking
    return "repos/%s/issues/%s/comments" % (repo_name, number)


def get_product_name(obs_project: str) -> str:
    product_match = re.search(".*:PullRequest:\\d+:(.*)", obs_project)
    return product_match.group(1) if product_match else ""


def get_product_name_and_version_from_scmsync(scmsync_url: str) -> Tuple[str, str]:
    m = re.search(".*/products/(.*)#(.*)", scmsync_url)
    return (m.group(1), m.group(2)) if m else ("", "")


def compute_repo_url(
    base: str,
    product_name: str,
    repo: Tuple[str, str, str],
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


def compute_repo_url_for_job_setting(base: str, repo: Repos) -> str:
    product_name = get_product_name(repo.version)
    return compute_repo_url(
        base,
        product_name,
        (repo.product, repo.version, repo.product_version),
        repo.arch,
        "",
    )


def get_open_prs(token: Dict[str, str], repo: str, dry: bool) -> List[Any]:
    if dry:
        return read_json("pulls")
    open_prs = []
    page = 1
    while True:
        # https://docs.gitea.com/api/1.20/#tag/repository/operation/repoListPullRequests
        prs_on_page = get_json(
            "repos/%s/pulls?state=open&page=%i" % (repo, page), token
        )
        if not isinstance(prs_on_page, list) or len(prs_on_page) <= 0:
            break
        open_prs.extend(prs_on_page)
        page += 1
    return open_prs


def review_pr(
    token: Dict[str, str],
    repo_name: str,
    pr_number: int,
    msg: str,
    commit_id: str,
    approve: bool = True,
):
    review_data = {
        "body": msg,
        "comments": [],
        "commit_id": commit_id,
        "event": "APPROVED" if approve else "REQUEST_CHANGES",
    }
    post_json(reviews_url(repo_name, pr_number), token, review_data)


def get_name(review: Dict[str, Any], of: str, via: str):
    entity = review.get(of)
    return entity.get(via, "") if entity is not None else ""


def add_reviews(incident: Dict[str, Any], reviews: List[Any]) -> int:
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
        if OBS_GROUP in (
            get_name(review, "user", "login"),  # concrete review via our bot account
            get_name(review, "team", "name"),  # review request for team bot is part of
        ):
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
        elif state in ("PENDING", "REQUEST_REVIEW"):
            pending += 1
    incident["approved"] = approvals > 0 and changes_requested + review_requested == 0
    incident["inReview"] = pending + pending_qam > 0
    incident["inReviewQAM"] = pending_qam > 0
    return reviews_by_qam


def add_build_result(
    incident: Dict[str, Any],
    res: Any,
    projects: Set[str],
    successful_packages: Set[str],
    unpublished_repos: Set[str],
    failed_packages: Set[str],
):
    state = res.get("state")
    project = res.get("project")
    product_name = get_product_name(project)
    arch = res.get("arch")
    channel = ":".join([project, arch])
    # read Git hash from scminfo element
    scm_info_key = "scminfo_" + product_name if len(product_name) != 0 else "scminfo"
    for scminfo_element in res.findall("scminfo"):
        found_scminfo = scminfo_element.text
        existing_scminfo = incident.get(scm_info_key, None)
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
    # read product version from scmsync element, e.g. 15.99
    for scmsync_element in res.findall("scmsync"):
        (_, product_version) = get_product_name_and_version_from_scmsync(
            scmsync_element.text
        )
        if len(product_version) > 0:
            channel = "#".join([channel, product_version])
            break
    projects.add(channel)
    # require only relevant projects to be built/published
    if product_name not in OBS_PRODUCTS:
        return
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


def get_multibuild_data(obs_project: str):
    r = MultibuildFlavorResolver(OBS_URL, obs_project, "000productcompose")
    return r.get_multibuild_data()


def determine_relevant_archs_from_multibuild_info(obs_project: str, dry: bool):
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
        except Exception as e:
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
            if arch in ("x86_64", "aarch64", "ppc64le", "s390x"):
                relevant_archs.add(arch)
    log.debug("Relevant archs for %s: %s", obs_project, str(sorted(relevant_archs)))
    return relevant_archs


def add_build_results(incident: Dict[str, Any], obs_urls: List[str], dry: bool):
    successful_packages = set()
    unpublished_repos = set()
    failed_packages = set()
    projects = set()
    for url in obs_urls:
        project_match = re.search(".*/project/show/(.*)", url)
        if project_match:
            obs_project = project_match.group(1)
            relevant_archs = determine_relevant_archs_from_multibuild_info(
                obs_project, dry
            )
            build_info_url = osc.core.makeurl(
                OBS_URL, ["build", obs_project, "_result"]
            )
            if dry:
                build_info = read_xml("build-results-124-" + obs_project)
            else:
                build_info = osc.util.xml.xml_parse(osc.core.http_GET(build_info_url))
            for res in build_info.getroot().findall("result"):
                if OBS_REPO_TYPE != "" and res.get("repository") != OBS_REPO_TYPE:
                    continue
                if relevant_archs is not None and res.get("arch") not in relevant_archs:
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
    incident["failed_or_unpublished_packages"] = [*failed_packages, *unpublished_repos]
    incident["successful_packages"] = [*successful_packages]
    if "scminfo" not in incident and len(OBS_PRODUCTS) == 1:
        incident["scminfo"] = incident.get("scminfo_" + next(iter(OBS_PRODUCTS)), "")


def add_comments_and_referenced_build_results(
    incident: Dict[str, Any],
    comments: List[Any],
    dry: bool,
):
    for comment in reversed(comments):
        body = comment["body"]
        user_name = comment["user"]["username"]
        if user_name == "autogits_obs_staging_bot":
            add_build_results(incident, re.findall("https://[^ ]*", body), dry)
            break


def add_packages_from_patchinfo(
    incident: Dict[str, Any], token: Dict[str, str], patch_info_url: str, dry: bool
):
    if dry:
        patch_info = read_xml("patch-info")
    else:
        patch_info = osc.util.xml.xml_fromstring(
            requests.get(patch_info_url, verify=False, headers=token).text
        )
    for res in patch_info.findall("package"):
        incident["packages"].append(res.text)


def add_packages_from_files(
    incident: Dict[str, Any], token: Dict[str, str], files: List[Any], dry: bool
):
    for file_info in files:
        file_name = file_info.get("filename", "").split("/")[-1]
        raw_url = file_info.get("raw_url")
        if file_name == "_patchinfo" and raw_url is not None:
            add_packages_from_patchinfo(incident, token, raw_url, dry)


def is_build_acceptable_and_log_if_not(incident: Dict[str, Any], number: int) -> bool:
    if len(incident["failed_or_unpublished_packages"]) > 0:
        log.info("Skipping PR %s, not all packages succeeded and published", number)
        return False
    if len(incident["successful_packages"]) < 1:
        log.info("Skipping PR %s, no packages have been built/published", number)
        return False
    return True


def make_incident_from_pr(
    pr: Dict[str, Any],
    token: Dict[str, str],
    only_successful_builds: bool,
    only_requested_prs: bool,
    dry: bool,
):
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
        add_comments_and_referenced_build_results(incident, comments, dry)
        if len(incident["channels"]) == 0:
            log.info("Skipping PR %s, no channels found/considered", number)
            return None
        if only_successful_builds and not is_build_acceptable_and_log_if_not(
            incident, number
        ):
            return None
        add_packages_from_files(incident, token, files, dry)
        if len(incident["packages"]) == 0:
            log.info("Skipping PR %s, no packages found/considered", number)
            return None

    except Exception as e:  # pylint: disable=broad-except
        log.error("Unable to process PR %s", pr.get("number", "?"))
        log.exception(e)
        return None
    return incident


def get_incidents_from_open_prs(
    open_prs: Set[int],
    token: Dict[str, str],
    only_successful_builds: bool,
    only_requested_prs: bool,
    dry: bool,
) -> List[Any]:
    incidents = []

    # configure osc to be able to request build info from OBS
    osc.conf.get_config(override_apiurl=OBS_URL)

    with CT.ThreadPoolExecutor() as executor:
        future_inc = [
            executor.submit(
                make_incident_from_pr,
                pr,
                token,
                only_successful_builds,
                only_requested_prs,
                dry,
            )
            for pr in open_prs
        ]
        for future in CT.as_completed(future_inc):
            incidents.append(future.result())

    incidents = [inc for inc in incidents if inc]
    return incidents
