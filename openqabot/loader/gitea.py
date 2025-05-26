# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import concurrent.futures as CT
from logging import getLogger
from typing import Any, List, Set, Dict
import re
import xml.etree.ElementTree as ET

import json
import urllib3
import urllib3.exceptions

import osc.conf
import osc.core
import osc.util.xml

from ..utils import retry10 as requests
from .. import GITEA, OBS_GROUP, OBS_URL

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


def read_json(name: str) -> Any:
    with open("responses/%s.json" % name, "r", encoding="utf8") as json_file:
        return json.loads(json_file.read())


def read_xml(name: str) -> Any:
    return ET.parse("responses/%s.xml" % name)


def reviews_url(repo_name: str, number: int):
    # https://docs.gitea.com/api/1.20/#tag/repository/operation/repoListPullReviews
    return "repos/%s/pulls/%s/reviews" % (repo_name, number)


def comments_url(repo_name: str, number: int):
    # https://docs.gitea.com/api/1.20/#tag/issue/operation/issueRemoveIssueBlocking
    return "repos/%s/issues/%s/comments" % (repo_name, number)


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


def add_reviews(incident: Dict[str, Any], reviews: List[Any]) -> int:
    approvals = 0
    changes_requested = 0
    review_requested = 0
    pending = 0
    pending_qam = 0
    reviews_by_qam = 0
    for review in reviews:
        # ignore stale and dismissed reviews
        if review.get("stale", True) or review.get("dismissed", True):
            continue
        # accumulate number of reviews per state
        state = review.get("state", "")
        team = review.get("team")
        if team is not None and team.get("name", "") == OBS_GROUP:
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
    successful_packages: set[str],
    unpublished_repos: set[str],
    failed_packages: set[str],
):
    state = res.get("state")
    if state != "published":
        unpublished_repos.add("@".join([res.get("project"), res.get("arch")]))
        return
    for scminfo_element in res.findall("scminfo"):
        found_scminfo = scminfo_element.text
        existing_scminfo = incident.get("scminfo", None)
        if len(found_scminfo) > 0:
            if existing_scminfo is None or found_scminfo == existing_scminfo:
                incident["scminfo"] = found_scminfo
            else:
                log.warning(
                    "Found inconsistent scminfo for PR %i, found '%s' and previously got '%s'",
                    incident["number"],
                    found_scminfo,
                    existing_scminfo,
                )
    for status in res.findall("status"):
        code = status.get("code")
        if code == "excluded":
            continue
        if code == "succeeded":
            successful_packages.add(status.get("package"))
        else:
            failed_packages.add(status.get("package"))


def add_build_results(
    incident: Dict[str, Any], obs_urls: List[str], only_successful: bool, dry: bool
):
    successful_packages = set()
    unpublished_repos = set()
    failed_packages = set()
    projects = set()
    for url in obs_urls:
        project_match = re.search(".*/project/show/(.*)", url)
        if project_match:
            build_info_url = osc.core.makeurl(
                OBS_URL, ["build", project_match.group(1), "_result"]
            )
            if dry:
                build_info = read_xml("build-results-124-" + project_match.group(1))
            else:
                build_info = osc.util.xml.xml_parse(osc.core.http_GET(build_info_url))
            for res in build_info.getroot().findall("result"):
                projects.add(":".join([res.get("project"), res.get("arch")]))
                add_build_result(
                    incident,
                    res,
                    successful_packages,
                    unpublished_repos,
                    failed_packages,
                )
    if len(unpublished_repos) > 0:
        log.warning(
            "Some repos for PR %i have not been published yet: %s",
            incident["number"],
            ", ".join(unpublished_repos),
        )
    if len(failed_packages) > 0:
        log.warning(
            "Some packages for PR %i have failed: %s",
            incident["number"],
            ", ".join(failed_packages),
        )
    incident["channels"] = [*projects]
    if not only_successful or len(failed_packages) + len(unpublished_repos) == 0:
        incident["packages"] = [*successful_packages]


def add_comments_and_referenced_build_results(
    incident: Dict[str, Any],
    comments: List[Any],
    only_successful_builds: bool,
    dry: bool,
):
    for comment in reversed(comments):
        body = comment["body"]
        user_name = comment["user"]["username"]
        if user_name == "autogits_obs_staging_bot":
            add_build_results(
                incident, re.findall("https://[^ ]*", body), only_successful_builds, dry
            )
            break


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
            else:
                reviews = []
                comments = []
        else:
            reviews = get_json(reviews_url(repo_name, number), token)
            comments = get_json(comments_url(repo_name, number), token)
        if add_reviews(incident, reviews) < 1 and only_requested_prs:
            log.info("Skipping PR %s, no review by ", number)
            return None
        add_comments_and_referenced_build_results(
            incident, comments, only_successful_builds, dry
        )
        if len(incident["packages"]) == 0:
            log.info("Skipping PR %s, no packages found/considered", number)
            return None
        if len(incident["channels"]) == 0:
            log.info("Skipping PR %s, no channels found/considered", number)
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
