# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import os
import re
from argparse import Namespace
from collections import defaultdict
from logging import getLogger
from pprint import pformat
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple

import osc.conf
import osc.core

from openqabot.openqa import openQAInterface

from . import DOWNLOAD_BASE, OBS_GROUP, OBS_URL
from .errors import PostOpenQAError
from .loader.incrementconfig import IncrementConfig
from .repodiff import Package, RepoDiff
from .utils import merge_dicts
from .utils import retry10 as retried_requests

log = getLogger("bot.increment_approver")
ok_results = {"passed", "softfailed"}
final_states = {"done", "cancelled"}
default_flavor = "Online-Increments"


class BuildInfo(NamedTuple):
    distri: str
    product: str
    version: str
    flavor: str
    arch: str
    build: str

    def __str__(self) -> str:
        return f"{self.product}v{self.version} build {self.build}@{self.arch} of flavor {self.flavor}"

    def string_with_params(self, params: Dict[str, str]) -> str:
        version = params.get("VERSION", self.version)
        flavor = params.get("FLAVOR", self.flavor)
        arch = params.get("ARCH", self.arch)
        build = params.get("BUILD", self.build)
        return f"{self.product}v{version} build {build}@{arch} of flavor {flavor}"


class ApprovalStatus(NamedTuple):
    request: osc.core.Request
    ok_jobs: Set[int] = set()  # noqa: RUF012 - Suggestion using ClassVar does not work; maybe a false positive.
    reasons_to_disapprove: List[str] = []  # noqa: RUF012 - Suggestion using ClassVar does not work; maybe a false positive.

    def add(self, ok_jobs: Set[int], reasons_to_disapprove: List[str]) -> None:
        self.ok_jobs.update(ok_jobs)
        self.reasons_to_disapprove.extend(reasons_to_disapprove)


class IncrementApprover:
    def __init__(self, args: Namespace) -> None:
        self.args = args
        self.token = {"Authorization": "Token {}".format(args.token)}
        self.client = openQAInterface(args)
        self.repo_diff = {}
        self.requests_to_approve = {}
        self.config = IncrementConfig.from_args(args)
        osc.conf.get_config(override_apiurl=OBS_URL)

    def _find_request_on_obs(self, config: IncrementConfig) -> Optional[osc.core.Request]:
        args = self.args
        relevant_states = ["new", "review"]
        if args.accepted:
            relevant_states.append("accepted")
        if args.request_id is None:
            build_project = config.build_project()
            log.debug(
                "Checking for product increment requests to be reviewed by %s on %s",
                OBS_GROUP,
                build_project,
            )
            obs_requests = osc.core.get_request_list(OBS_URL, project=build_project, req_state=relevant_states)
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
            log.info("Skipping approval, no relevant requests in states %s", "/".join(relevant_states))
        else:
            log.debug("Found request %s", relevant_request.id)
            if hasattr(relevant_request.state, "to_xml"):
                log.debug(relevant_request.to_str())
        return relevant_request

    def _request_openqa_job_results(
        self,
        build_info: BuildInfo,
        params: List[Dict[str, str]],
    ) -> List[Dict[str, Dict[str, Dict[str, Any]]]]:
        log.debug("Checking openQA job results for %s", build_info)
        query_params = (
            {
                "distri": p["DISTRI"],
                "version": p["VERSION"],
                "flavor": p["FLAVOR"],
                "arch": p["ARCH"],
                "build": p["BUILD"],
            }
            for p in params
        )
        res = [self.client.get_scheduled_product_stats(p) for p in query_params]
        log.debug("Job statistics:\n%s", pformat(res))
        return res

    def _check_openqa_jobs(
        self,
        results: List[Dict[str, Dict[str, Dict[str, Any]]]],
        build_info: BuildInfo,
        params: List[Dict[str, str]],
    ) -> Optional[bool]:
        actual_states = set(next((res.keys() for res in results), []))
        pending_states = actual_states - final_states
        if len(actual_states) == 0:
            log.info(
                "Skipping approval, there are no relevant jobs on openQA for %s",
                build_info.string_with_params(params[0] if len(params) > 0 else {}),
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
        self,
        results: Dict[str, Dict[str, Dict[str, Any]]],
        ok_jobs: Set[int],
        not_ok_jobs: Dict[str, Set[str]],
    ) -> None:
        for state in final_states:
            for result, info in results.get(state, {}).items():
                if result in ok_results:
                    ok_jobs.update(set(info["job_ids"]))
                else:
                    not_ok_jobs[result].update(info["job_ids"])

    def _evaluate_list_of_openqa_job_results(
        self,
        list_of_results: List[Dict[str, Dict[str, Dict[str, Any]]]],
    ) -> Tuple[Set[int], List[str]]:
        ok_jobs = set()  # keep track of ok jobs
        not_ok_jobs = defaultdict(set)  # keep track of not ok jobs
        openqa_url = self.client.url.geturl()
        for results in list_of_results:
            self._evaluate_openqa_job_results(results, ok_jobs, not_ok_jobs)
        reasons_to_disapprove = []  # compose list of blocking jobs
        for result, job_ids in not_ok_jobs.items():
            job_list = "\n".join((f" - {openqa_url}/tests/{i}" for i in job_ids))
            reasons_to_disapprove.append(f"The following openQA jobs ended up with result '{result}':\n{job_list}")
        return (ok_jobs, reasons_to_disapprove)

    def _handle_approval(self, approval_status: ApprovalStatus) -> int:
        reasons_to_disapprove = approval_status.reasons_to_disapprove
        if len(reasons_to_disapprove) == 0:
            message = "All %i jobs on openQA have %s" % (
                len(approval_status.ok_jobs),
                "/".join(sorted(ok_results)),
            )
            if not self.args.dry:
                osc.core.change_review_state(
                    apiurl=OBS_URL,
                    reqid=str(approval_status.request.reqid),
                    newstate="accepted",
                    by_group=OBS_GROUP,
                    message=message,
                )
        else:
            message = "Not approving for the following reasons:\n" + "\n".join(reasons_to_disapprove)
        log.info(message)
        return 0

    def _determine_build_info(self, config: IncrementConfig) -> Set[BuildInfo]:
        # deduce DISTRI, VERSION, FLAVOR, ARCH and BUILD from the spdx files in the repo listing similar to the sync plugin
        build_project_url = config.build_project_url()
        sub_path = config.build_listing_sub_path
        url = f"{build_project_url}/{sub_path}/?jsontable=1"
        log.debug("Checking for '%s' files on %s", config.build_regex, url)
        rows = retried_requests.get(url).json().get("data", [])
        res = set()
        for row in rows:
            name = row.get("name", "")
            log.debug("Found file: %s", name)
            m = re.search(config.build_regex, name)
            if m:
                product = m.group("product")
                if not re.search(config.product_regex, product):
                    continue  # skip if this config doesn't apply to the product
                distri = config.distri
                version = m.group("version")
                arch = m.group("arch")
                build = m.group("build")
                try:
                    flavor = m.group("flavor") + "-Increments"
                except IndexError:
                    flavor = default_flavor
                if (
                    config.distri in {"any", distri}
                    and config.flavor in {"any", flavor}
                    and config.version in {"any", version}
                ):
                    res.add(BuildInfo(distri, product, version, flavor, arch, build))
        return res

    def _extra_builds_for_package(
        self,
        package: Package,
        config: IncrementConfig,
        build_info: BuildInfo,
    ) -> Optional[Dict[str, str]]:
        for additional_build in config.additional_builds:
            package_name_regex = additional_build.get("package_name_regex", additional_build.get("regex"))
            package_name_match = re.search(package_name_regex, package.name) if package_name_regex is not None else None
            if not package_name_match:
                continue
            package_version_regex = additional_build.get("package_version_regex")
            if package_version_regex is not None and not re.search(package_version_regex, package.version):
                continue
            extra_build = [build_info.build, additional_build["build_suffix"]]
            extra_params = {}
            try:
                kind = package_name_match.group("kind")
                if kind != "default":
                    extra_build.append(kind)
            except IndexError:
                pass
            try:
                kernel_version = package_name_match.group("kernel_version").replace("_", ".")
                extra_build.append(kernel_version)
                extra_params["KERNEL_VERSION"] = kernel_version
            except IndexError:
                pass
            extra_params["BUILD"] = "-".join(extra_build)
            extra_params.update(additional_build["settings"])
            return extra_params
        return None

    def _extra_builds_for_additional_builds(
        self,
        package_diff: Set[Package],
        config: IncrementConfig,
        build_info: BuildInfo,
    ) -> List[Dict[str, str]]:
        def handle_package(p: Package) -> Optional[Dict[str, str]]:
            return self._extra_builds_for_package(p, config, build_info)

        extra_builds = map(handle_package, package_diff)
        return [*filter(lambda b: b is not None, extra_builds)]

    @staticmethod
    def _populate_params_from_env(params: Dict[str, str], env_var: str) -> None:
        value = os.environ.get(env_var, "")
        if len(value) > 0:
            params["__" + env_var] = value

    @staticmethod
    def _match_packages(package_diff: Set[Package], packages_to_find: List[str]) -> bool:
        if len(packages_to_find) == 0:
            return True
        names_of_changed_packages = {p.name for p in package_diff}
        return any(package in names_of_changed_packages for package in packages_to_find)

    def _make_scheduling_parameters(self, config: IncrementConfig, build_info: BuildInfo) -> List[Dict[str, str]]:
        repo_sub_path = "/product"
        base_params = {
            "DISTRI": build_info.distri,
            "VERSION": build_info.version,
            "FLAVOR": build_info.flavor,
            "ARCH": build_info.arch,
            "BUILD": build_info.build,
            "INCREMENT_REPO": config.build_project_url(DOWNLOAD_BASE) + repo_sub_path,
        }
        IncrementApprover._populate_params_from_env(base_params, "CI_JOB_URL")
        base_params.update(config.settings)
        extra_params = []
        if config.diff_project_suffix != "none":
            build_project = config.build_project() + repo_sub_path
            diff_project = config.diff_project()
            diff_key = f"{build_project}:{diff_project}"
            repo_diff = self.repo_diff.get(diff_key)
            if repo_diff is None:
                log.debug("Comuting diff to project %s", diff_project)
                repo_diff = RepoDiff(self.args).compute_diff(diff_project, build_project)[0]
                self.repo_diff[diff_key] = repo_diff
            relevant_diff = repo_diff[build_info.arch] | repo_diff["noarch"]
            # schedule base params if package filter is empty for matching
            if IncrementApprover._match_packages(relevant_diff, config.packages):
                extra_params.append({})
            # schedule additional builds based on changed packages
            extra_params.extend(self._extra_builds_for_additional_builds(relevant_diff, config, build_info))
        else:
            # schedule always just base params if not computing the package diff
            extra_params.append({})
        return [*(merge_dicts(base_params, p) for p in extra_params)]

    def _schedule_openqa_jobs(self, build_info: BuildInfo, params: List[Dict[str, str]]) -> int:
        error_count = 0
        for p in params:
            log.info("Scheduling jobs for %s", build_info.string_with_params(p))
            if self.args.dry:
                log.info(p)
                continue
            try:
                self.client.post_job(p)
            except PostOpenQAError:
                error_count += 1
        return error_count

    def _process_request_for_config(self, request: Optional[osc.core.Request], config: IncrementConfig) -> int:
        error_count = 0
        if request is None:
            return error_count
        request_id = request.reqid
        requests_to_approve = self.requests_to_approve
        if request_id in requests_to_approve:
            approval_status = requests_to_approve[request_id]
        else:
            approval_status = ApprovalStatus(request)
            requests_to_approve[request_id] = approval_status
        for build_info in self._determine_build_info(config):
            if len(config.archs) > 0 and build_info.arch not in config.archs:
                continue
            params = self._make_scheduling_parameters(config, build_info)
            if len(params) < 1:
                log.info("Skipping %s for %s, filtered out via 'packages' or 'archs' setting", config, build_info)
                continue
            info_str = build_info.string_with_params(params[0])
            res = self._request_openqa_job_results(build_info, params)
            if self.args.reschedule:
                approval_status.reasons_to_disapprove.append("Re-scheduling jobs for " + info_str)
                error_count += self._schedule_openqa_jobs(build_info, params)
                continue
            openqa_jobs_ready = self._check_openqa_jobs(res, build_info, params)
            if openqa_jobs_ready is None:
                approval_status.reasons_to_disapprove.append("No jobs scheduled for " + info_str)
                if self.args.schedule:
                    error_count += self._schedule_openqa_jobs(build_info, params)
                continue
            if openqa_jobs_ready:
                approval_status.add(*(self._evaluate_list_of_openqa_job_results(res)))
            else:
                approval_status.reasons_to_disapprove.append("Not all jobs ready for " + info_str)
        return error_count

    def __call__(self) -> int:
        error_count = 0
        for config in self.config:
            request = self._find_request_on_obs(config)
            error_count += self._process_request_for_config(request, config)
        for request in self.requests_to_approve.values():
            error_count += self._handle_approval(request)
        return error_count
