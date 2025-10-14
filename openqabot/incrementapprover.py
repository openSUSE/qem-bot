# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from typing import Any, Dict, List, Tuple, Optional, Set, NamedTuple
import re
from logging import getLogger
from pprint import pformat

import osc.conf
import osc.core

from openqabot.openqa import openQAInterface

from .errors import PostOpenQAError
from .repodiff import Package, RepoDiff
from .utils import retry10 as requests
from . import OBS_GROUP, OBS_URL, OBS_DOWNLOAD_URL

log = getLogger("bot.increment_approver")
ok_results = set(("passed", "softfailed"))
final_states = set(("done", "cancelled"))
default_flavor = "Online-Increments"


class BuildInfo(NamedTuple):
    distri: str
    product: str
    version: str
    flavor: str
    arch: str
    build: str

    def __str__(self):
        return f"{self.product}v{self.version} build {self.build}@{self.arch} of flavor {self.flavor}"


class IncrementApprover:
    def __init__(self, args: Namespace) -> None:
        self.args = args
        self.token = {"Authorization": "Token {}".format(args.token)}
        self.client = openQAInterface(args)
        self.repo_diff = None
        osc.conf.get_config(override_apiurl=OBS_URL)

    def _find_request_on_obs(self) -> Optional[osc.core.Request]:
        args = self.args
        relevant_states = ["new", "review"]
        if args.accepted:
            relevant_states.append("accepted")
        if args.request_id is None:
            log.debug(
                "Checking for product increment requests to be reviewed by %s on %s",
                OBS_GROUP,
                args.obs_project,
            )
            obs_requests = osc.core.get_request_list(
                OBS_URL, project=args.obs_project, req_state=relevant_states
            )
            relevant_request = None
            for request in sorted(obs_requests, reverse=True):
                for review in request.reviews:
                    if review.by_group == OBS_GROUP and review.state in relevant_states:
                        relevant_request = request
                        break
        else:
            log.debug("Checking specified request %i", args.request_id)
            relevant_request = osc.core.get_request(OBS_URL, str(args.request_id))
        if relevant_request is None:
            log.info(
                "Skipping approval, no relevant requests in states "
                + "/".join(relevant_states)
            )
        else:
            log.debug("Found request %s", relevant_request.id)
            if hasattr(relevant_request.state, "to_xml"):
                log.debug(relevant_request.to_str())
        return relevant_request

    def _request_openqa_job_results(
        self, build_info: BuildInfo
    ) -> Dict[str, Dict[str, Dict[str, Any]]]:
        log.debug("Checking openQA job results for %s", build_info)
        params = {
            "distri": build_info.distri,
            "version": build_info.version,
            "flavor": build_info.flavor,
            "arch": build_info.arch,
            "build": build_info.build,
        }
        res = self.client.get_scheduled_product_stats(params)
        log.debug("Job statistics:\n%s", pformat(res))
        return res

    def _check_openqa_jobs(
        self, res: Dict[str, Dict[str, Dict[str, Any]]], build_info: BuildInfo
    ) -> Optional[bool]:
        actual_states = set(res.keys())
        pending_states = actual_states - final_states
        if len(actual_states) == 0:
            log.info(
                "Skipping approval, there are no relevant jobs on openQA for %s",
                build_info,
            )
            return None
        if len(pending_states):
            log.info(
                "Skipping approval, some jobs on openQA for %s are in pending states (%s)",
                build_info,
                ", ".join(sorted(pending_states)),
            )
            return False
        return True

    def _evaluate_openqa_job_results(
        self, res: Dict[str, Dict[str, Dict[str, Any]]]
    ) -> Tuple[int, List[str]]:
        ok_jobs = 0  # # count ok jobs
        reasons_to_disapprove = []  # compose list of blocking jobs
        openqa_url = self.client.url.geturl()
        for state in final_states:
            for result, info in res.get(state, {}).items():
                if result in ok_results:
                    ok_jobs += 1
                else:
                    job_list = "\n".join(
                        map(lambda id: f" - {openqa_url}/tests/{id}", info["job_ids"])
                    )
                    reasons_to_disapprove.append(
                        f"The following openQA jobs ended up with result '{result}':\n{job_list}"
                    )
        return (ok_jobs, reasons_to_disapprove)

    def _handle_approval(
        self, request: osc.core.Request, ok_jobs: int, reasons_to_disapprove: List[str]
    ) -> int:
        if len(reasons_to_disapprove) == 0:
            message = "All %i jobs on openQA have %s" % (
                ok_jobs,
                "/".join(sorted(ok_results)),
            )
            if not self.args.dry:
                osc.core.change_review_state(
                    apiurl=OBS_URL,
                    reqid=str(request.id),
                    newstate="accepted",
                    by_group=OBS_GROUP,
                    message=message,
                )
        else:
            message = "Not approving for the following reasons:\n" + "\n".join(
                reasons_to_disapprove
            )
        log.info(message)
        return 0

    def _map_product_to_openqa_distri(self, product: str) -> Optional[str]:
        if product.startswith("SLE"):
            return "sle"
        if product.startswith("SL-Micro"):
            return "sle-micro"
        return None

    def _determine_build_info(self) -> Set[BuildInfo]:
        # deduce DISTRI, VERSION, FLAVOR, ARCH and BUILD from the spdx files in the repo listing similar to the sync plugin
        args = self.args
        base_path = args.obs_project.replace(":", ":/")
        sub_path = args.build_listing_sub_path
        url = f"{OBS_DOWNLOAD_URL}/{base_path}/{sub_path}/?jsontable=1"
        log.debug("Checking for '%s' files on %s", args.build_regex, url)
        rows = requests.get(url).json().get("data", [])
        res = set()
        for row in rows:
            name = row.get("name", "")
            log.debug("Found file: %s", name)
            m = re.search(args.build_regex, name)
            if m:
                product = m.group("product")
                distri = self._map_product_to_openqa_distri(product)
                if distri is None:
                    continue  # skip unknown products
                version = m.group("version")
                arch = m.group("arch")
                build = m.group("build")
                try:
                    flavor = m.group("flavor") + "-Increments"
                except IndexError:
                    flavor = default_flavor
                if (
                    args.distri in ("any", distri)
                    and args.flavor in ("any", flavor)
                    and args.version in ("any", version)
                ):
                    res.add(BuildInfo(distri, product, version, flavor, arch, build))
        return res

    def _extra_builds_for_kernel_livepatching(
        self, package_diff: Set[Package], build_info: BuildInfo
    ) -> List[Dict[str, str]]:
        extra_builds = []
        for package in package_diff:
            m = re.search(
                "kernel-livepatch-(?P<version>[^\\-]*?-[^\\-]*?)-(?P<kind>.*)",
                package.name,
            )
            if not m:
                continue
            extra_build = [build_info.build, "kernel-livepatch"]
            kernel_version = []
            kind = m.group("kind")
            if kind != "default":
                extra_build.append(kind)
            kernel_version.append(m.group("version").replace("_", "."))
            extra_build.extend(kernel_version)
            extra_builds.append(
                {
                    "BUILD": "-".join(extra_build),
                    "KERNEL_VERSION": "-".join(kernel_version),
                    "KGRAFT": "1",
                }
            )
        return extra_builds

    def _schedule_openqa_jobs(self, build_info: BuildInfo) -> int:
        log.info("Scheduling jobs for %s", build_info)
        base_params = {
            "DISTRI": build_info.distri,
            "VERSION": build_info.version,
            "FLAVOR": build_info.flavor,
            "ARCH": build_info.arch,
            "BUILD": build_info.build,
        }
        builds = [{}]
        base_repo = self.args.compute_diff_to
        if base_repo != "none":
            if self.repo_diff is None:
                self.repo_diff = RepoDiff(self.args).compute_diff(
                    base_repo, self.args.obs_project
                )[0]
            relevant_diff = self.repo_diff[build_info.arch] | self.repo_diff["noarch"]
            builds.extend(
                self._extra_builds_for_kernel_livepatching(relevant_diff, build_info)
            )
        error_count = 0
        for build_params in builds:
            params = base_params | build_params
            if self.args.dry:
                log.info(params)
                continue
            try:
                self.client.post_job(params)
            except PostOpenQAError:
                error_count += 1
        return error_count

    def __call__(self) -> int:
        error_count = 0
        request = self._find_request_on_obs()
        if request is None:
            return error_count
        for build_info in self._determine_build_info():
            res = self._request_openqa_job_results(build_info)
            if self.args.reschedule:
                error_count += self._schedule_openqa_jobs(build_info)
                continue
            openqa_jobs_ready = self._check_openqa_jobs(res, build_info)
            if openqa_jobs_ready is None and self.args.schedule:
                error_count += self._schedule_openqa_jobs(build_info)
                continue
            if not openqa_jobs_ready:
                continue
            error_count += self._handle_approval(
                request, *(self._evaluate_openqa_job_results(res))
            )
        return error_count
