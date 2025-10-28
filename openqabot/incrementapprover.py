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
from .utils import retry10 as requests

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

    def __str__(self):
        return f"{self.product}v{self.version} build {self.build}@{self.arch} of flavor {self.flavor}"

    def string_with_params(self, params: Dict[str, str]) -> str:
        version = params.get("VERSION", self.version)
        flavor = params.get("FLAVOR", self.flavor)
        arch = params.get("ARCH", self.arch)
        build = params.get("BUILD", self.build)
        return f"{self.product}v{version} build {build}@{arch} of flavor {flavor}"


class IncrementApprover:
    def __init__(self, args: Namespace) -> None:
        self.args = args
        self.token = {"Authorization": "Token {}".format(args.token)}
        self.client = openQAInterface(args)
        self.repo_diff = None
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
            log.info("Skipping approval, no relevant requests in states " + "/".join(relevant_states))
        else:
            log.debug("Found request %s", relevant_request.id)
            if hasattr(relevant_request.state, "to_xml"):
                log.debug(relevant_request.to_str())
        return relevant_request

    def _request_openqa_job_results(
        self, build_info: BuildInfo, params: List[Dict[str, str]]
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
        self, results: List[Dict[str, Dict[str, Dict[str, Any]]]], build_info: BuildInfo, params: List[Dict[str, str]]
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
        not_ok_jobs: Dict[str, Set[str]],
    ) -> int:
        ok_jobs = 0
        for state in final_states:
            for result, info in results.get(state, {}).items():
                if result in ok_results:
                    ok_jobs += 1
                else:
                    not_ok_jobs[result].update(info["job_ids"])
        return ok_jobs

    def _evaluate_list_of_openqa_job_results(
        self, list_of_results: List[Dict[str, Dict[str, Dict[str, Any]]]]
    ) -> Tuple[int, List[str]]:
        ok_jobs = 0  # count ok jobs
        not_ok_jobs = defaultdict(set)  # keep track of not ok jobs
        openqa_url = self.client.url.geturl()
        for results in list_of_results:
            ok_jobs += self._evaluate_openqa_job_results(results, not_ok_jobs)
        reasons_to_disapprove = []  # compose list of blocking jobs
        for result, job_ids in not_ok_jobs.items():
            job_list = "\n".join((f" - {openqa_url}/tests/{id}" for id in job_ids))
            reasons_to_disapprove.append(f"The following openQA jobs ended up with result '{result}':\n{job_list}")
        return (ok_jobs, reasons_to_disapprove)

    def _handle_approval(self, request: osc.core.Request, ok_jobs: int, reasons_to_disapprove: List[str]) -> int:
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
            message = "Not approving for the following reasons:\n" + "\n".join(reasons_to_disapprove)
        log.info(message)
        return 0

    def _determine_build_info(self, config: IncrementConfig) -> Set[BuildInfo]:
        # deduce DISTRI, VERSION, FLAVOR, ARCH and BUILD from the spdx files in the repo listing similar to the sync plugin
        build_project_url = config.build_project_url()
        sub_path = config.build_listing_sub_path
        url = f"{build_project_url}/{sub_path}/?jsontable=1"
        log.debug("Checking for '%s' files on %s", config.build_regex, url)
        rows = requests.get(url).json().get("data", [])
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
                    config.distri in ("any", distri)
                    and config.flavor in ("any", flavor)
                    and config.version in ("any", version)
                ):
                    res.add(BuildInfo(distri, product, version, flavor, arch, build))
        return res

    def _extra_builds_for_package(
        self, package: Package, config: IncrementConfig, build_info: BuildInfo
    ) -> Optional[Dict[str, str]]:
        for additional_build in config.additional_builds:
            m = re.search(additional_build["regex"], package.name)
            if not m:
                continue
            extra_build = [build_info.build, additional_build["build_suffix"]]
            extra_params = {}
            try:
                kind = m.group("kind")
                if kind != "default":
                    extra_build.append(kind)
            except IndexError:
                pass
            try:
                kernel_version = m.group("kernel_version").replace("_", ".")
                extra_build.append(kernel_version)
                extra_params["KERNEL_VERSION"] = kernel_version
            except IndexError:
                pass
            extra_params["BUILD"] = "-".join(extra_build)
            extra_params.update(additional_build["settings"])
            return extra_params
        return None

    def _extra_builds_for_additional_builds(
        self, package_diff: Set[Package], config: IncrementConfig, build_info: BuildInfo
    ) -> List[Dict[str, str]]:
        def handle_package(p):
            return self._extra_builds_for_package(p, config, build_info)

        extra_builds = map(handle_package, package_diff)
        return [*filter(lambda b: b is not None, extra_builds)]

    @staticmethod
    def _populate_params_from_env(params: Dict[str, str], env_var: str):
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
            diff_project = config.diff_project()
            if self.repo_diff is None:
                log.debug("Comuting diff to project %s", diff_project)
                self.repo_diff = RepoDiff(self.args).compute_diff(diff_project, config.build_project() + repo_sub_path)[
                    0
                ]
            relevant_diff = self.repo_diff[build_info.arch] | self.repo_diff["noarch"]
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
        for build_info in self._determine_build_info(config):
            if len(config.archs) > 0 and build_info.arch not in config.archs:
                continue
            params = self._make_scheduling_parameters(config, build_info)
            res = self._request_openqa_job_results(build_info, params)
            if self.args.reschedule:
                error_count += self._schedule_openqa_jobs(build_info, params)
                continue
            openqa_jobs_ready = self._check_openqa_jobs(res, build_info, params)
            if openqa_jobs_ready is None and self.args.schedule:
                error_count += self._schedule_openqa_jobs(build_info, params)
                continue
            if not openqa_jobs_ready:
                continue
            error_count += self._handle_approval(request, *(self._evaluate_list_of_openqa_job_results(res)))
        return error_count

    def __call__(self) -> int:
        error_count = 0
        for config in self.config:
            request = self._find_request_on_obs(config)
            error_count += self._process_request_for_config(request, config)
            self.repo_diff = None
        return error_count
