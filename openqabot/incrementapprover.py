# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Increment Approver."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from functools import lru_cache
from itertools import chain
from logging import getLogger
from pprint import pformat
from typing import TYPE_CHECKING, Any, cast

import osc.conf
import osc.core

from openqabot import config
from openqabot.config import OBSOLETE_PARAMS
from openqabot.openqa import OpenQAInterface

from .errors import AmbiguousApprovalStatusError, PostOpenQAError
from .loader.buildinfo import load_build_info
from .loader.incrementconfig import IncrementConfig
from .loader.sourcereport import compute_packages_of_request_from_source_report
from .repodiff import Package, RepoDiff
from .requests import find_request_on_obs
from .types.increment import ApprovalStatus, BuildInfo
from .utils import merge_dicts

if TYPE_CHECKING:
    from argparse import Namespace

log = getLogger("bot.increment_approver")
ok_results = {"passed", "softfailed"}
final_states = {"done", "cancelled"}
default_flavor_suffix = "Increments"
default_flavor = "Online"


OpenQAResult = dict[str, dict[str, dict[str, Any]]]
OpenQAResults = list[OpenQAResult]
ScheduleParams = list[dict[str, str]]


class IncrementApprover:
    """Logic for approving product increments."""

    def __init__(self, args: Namespace) -> None:
        """Initialize the IncrementApprover class."""
        self.args = args
        self.token = {"Authorization": f"Token {args.token}"}
        self.client = OpenQAInterface(args)
        self.package_diff = {}
        self.requests_to_approve = {}
        # safeguard us from using same job ID for 2 requests
        self.unique_jobid_request_pair = {}
        self.config = IncrementConfig.from_args(args)
        osc.conf.get_config(override_apiurl=config.settings.obs_url)

    def check_unique_jobid_request_pair(self, jobids: list[int], request: osc.core.Request) -> None:
        """Check if certain openQA job was already used to verify certain request ID.

           By design it should not happen and means some bug needs investigation.

        Args:
            jobids (list[int]): list of openQA job IDs
            request (_type_): OBS request

        Raises:
            AmbiguousApprovalStatusError: raised when some job is used second time for different request ID

        """
        for jobid in jobids:
            self.unique_jobid_request_pair.setdefault(jobid, request.reqid)
            if self.unique_jobid_request_pair[jobid] != request.reqid:
                raise AmbiguousApprovalStatusError

    @staticmethod
    @lru_cache(maxsize=128)
    def get_regex_match(pattern: str, string: str) -> re.Match | None:
        """Compile and match a regex pattern."""
        match = None
        try:
            match = re.search(pattern, string)
        except re.error:
            log.warning(
                "Pattern `%s` did not compile successfully. Considering as non-match and returning empty result.",
                pattern,
            )
        return match

    def request_openqa_job_results(self, params: ScheduleParams, info_str: str) -> OpenQAResults:
        """Fetch results from openQA for the specified scheduling parameters."""
        log.debug("Checking openQA job results for %s", info_str)
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

    @staticmethod
    def check_openqa_jobs(results: OpenQAResults, build_info: BuildInfo, params: ScheduleParams) -> bool | None:
        """Check if all openQA jobs are finished."""
        actual_states = {state for result in results for state in result}
        pending_states = actual_states - final_states
        if len(actual_states) == 0:
            build_info.log_no_jobs(params)
            return None
        if len(pending_states):
            build_info.log_pending_jobs(pending_states)
            return False
        return True

    def evaluate_openqa_job_results(
        self, results: OpenQAResult, ok_jobs: set[int], not_ok_jobs: dict[str, set[str]], request: osc.core.Request
    ) -> None:
        """Evaluate openQA job results and sort them into ok and not_ok sets."""
        all_items = chain.from_iterable(results.get(s, {}).items() for s in final_states)
        for result, info in all_items:
            destination = ok_jobs if result in ok_results else not_ok_jobs[result]
            self.check_unique_jobid_request_pair(info["job_ids"], request)
            destination.update(info["job_ids"])

    def evaluate_list_of_openqa_job_results(
        self, list_of_results: OpenQAResults, request: osc.core.Request
    ) -> tuple[set[int], list[str]]:
        """Evaluate a list of openQA job results."""
        ok_jobs = set()  # keep track of ok jobs
        not_ok_jobs = defaultdict(set)  # keep track of not ok jobs
        openqa_url = self.client.url.geturl()
        for results in list_of_results:
            self.evaluate_openqa_job_results(results, ok_jobs, not_ok_jobs, request)
        reasons_to_disapprove = [
            f"The following openQA jobs ended up with result '{result}':\n"
            + "\n".join(f" - {openqa_url}/tests/{i}" for i in job_ids)
            for result, job_ids in not_ok_jobs.items()
        ]
        return (ok_jobs, reasons_to_disapprove)

    def approve_on_obs(self, reqid: str, msg: str) -> None:
        """Change the review state of a request on OBS to accepted."""
        if self.args.dry:
            return
        osc.core.change_review_state(
            apiurl=config.settings.obs_url,
            reqid=reqid,
            newstate="accepted",
            by_group=config.settings.obs_group,
            message=msg,
        )

    def handle_approval(self, approval_status: ApprovalStatus) -> int:
        """Process approval or disapproval based on job results."""
        reasons_to_disapprove = approval_status.reasons_to_disapprove
        reqid = approval_status.request.reqid
        id_msg = f"OBS request ID '{reqid}'"

        if len(reasons_to_disapprove) == 0 and len(approval_status.ok_jobs) == 0:
            reasons_to_disapprove.append("No openQA jobs were found/checked for this request.")

        if len(reasons_to_disapprove) == 0:
            results_str = "/".join(sorted(ok_results))
            message = f"All {len(approval_status.ok_jobs)} openQA jobs have {results_str}"
            self.approve_on_obs(str(reqid), message)
            log.info("Approving %s: %s", id_msg, message)
        else:
            reasons_str = "\n\t".join(reasons_to_disapprove)
            end_str = f"End of reasons for not approving {id_msg}"
            log.info("Not approving %s for the following reasons:\n\t%s\n%s", id_msg, reasons_str, end_str)
        return 0

    def _match_additional_build(
        self,
        package: Package,
        additional_build: dict[str, Any],
        build_info: BuildInfo,
    ) -> dict[str, str] | None:
        """Check if an additional build matches a package and return extra parameters."""
        package_name_match = self._match_package_name_and_version(package, additional_build)
        if package_name_match is None:
            return None

        groups = package_name_match.groupdict()
        extra_build = [build_info.build, additional_build["build_suffix"]]
        extra_params: dict[str, str] = {}

        if (kind := groups.get("kind")) and kind != "default":
            extra_build.append(kind)

        if kernel_version := groups.get("kernel_version"):
            kernel_version = kernel_version.replace("_", ".")
            extra_build.append(kernel_version)
            extra_params["KERNEL_VERSION"] = kernel_version

        extra_params["BUILD"] = "-".join(extra_build)
        extra_params.update(cast("dict[str, str]", additional_build["settings"]))
        return extra_params

    def _match_package_name_and_version(self, package: Package, additional_build: dict[str, Any]) -> re.Match | None:
        """Match package name and version against regexes."""
        package_name_regex = additional_build.get("package_name_regex") or additional_build.get("regex", "")
        match = self.get_regex_match(package_name_regex, package.name)
        if match is None:
            return None
        package_version_regex = additional_build.get("package_version_regex")
        if package_version_regex is not None and not self.get_regex_match(package_version_regex, package.version):
            return None
        return match

    def extra_builds_for_package(
        self,
        package: Package,
        config_inc: IncrementConfig,
        build_info: BuildInfo,
    ) -> dict[str, str] | None:
        """Determine extra build parameters for a specific package."""
        if re.match(r"^1(?:\..*)?$", package.version):
            return None
        if "-debuginfo" in package.name or package.arch in {"src", "nosrc"}:
            return None

        for additional_build in config_inc.additional_builds:
            if (res := self._match_additional_build(package, additional_build, build_info)) is not None:
                return res
        return None

    def extra_builds_for_additional_builds(
        self,
        package_diff: set[Package],
        config_inc: IncrementConfig,
        build_info: BuildInfo,
    ) -> list[dict[str, str]]:
        """Determine extra builds for all additional builds in the configuration."""

        def handle_package(p: Package) -> dict[str, str] | None:
            return self.extra_builds_for_package(p, config_inc, build_info)

        return [b for p in package_diff if (b := handle_package(p)) is not None]

    @staticmethod
    def populate_params_from_env(params: dict[str, str], env_var: str) -> None:
        """Populate parameters from an environment variable."""
        value = os.environ.get(env_var, "")
        if len(value) > 0:
            params["__" + env_var] = value

    @staticmethod
    def match_packages(package_diff: set[Package], packages_to_find: list[str]) -> bool:
        """Check if any of the packages to find are present in the package diff."""
        if len(packages_to_find) == 0:
            return True
        names_of_changed_packages = {p.name for p in package_diff}
        return any(package in names_of_changed_packages for package in packages_to_find)

    def get_package_diff_from_source_report(self, request: osc.core.Request) -> defaultdict[str, set[Package]]:
        """Compute package diff using source reports."""
        diff_key = "request:" + str(request.id)
        package_diff = self.package_diff.get(diff_key)
        if package_diff is None:
            log.info("Computing source report diff for OBS request ID %s", request.id)
            package_diff = compute_packages_of_request_from_source_report(request)[0]
            log.debug("Packages updated by OBS request ID %s: %s", request.id, pformat(package_diff))
            self.package_diff[diff_key] = package_diff
        return package_diff

    @staticmethod
    def _get_diff_project(config_inc: IncrementConfig, build_info: BuildInfo | None) -> tuple[str, bool]:
        """Return the project to compute diff against and whether it is a reference repo."""
        diff_project = config_inc.diff_project()
        if build_info and build_info.flavor in config_inc.reference_repos:
            return config_inc.reference_repos[build_info.flavor], True
        return diff_project, False

    def get_package_diff_from_repo(
        self, config_inc: IncrementConfig, repo_sub_path: str, build_info: BuildInfo | None = None
    ) -> defaultdict[str, set[Package]]:
        """Compute package diff by comparing repositories."""
        build_project = config_inc.build_project() + repo_sub_path
        diff_project, is_reference_repo = self._get_diff_project(config_inc, build_info)

        if build_info and is_reference_repo:
            channel = build_info.flavor.removesuffix(f"-{config_inc.flavor_suffix}")
            build_project = f"{build_project}/{channel}/{build_info.arch}"
            diff_project = f"{diff_project}/{build_info.version}/{config_inc.diff_project_suffix}/{build_info.arch}"

        if not is_reference_repo and any(s in diff_project for s in ("-Debug", "-Source")):
            log.debug("Skipping repo diffing for %s (contains -Debug or -Source)", diff_project)
            return defaultdict(set)

        diff_key = f"{build_project}:{diff_project}"
        if diff_key in self.package_diff:
            return self.package_diff[diff_key]

        log.debug("Comuting repo diff to project %s", diff_project)
        package_diff = RepoDiff(self.args).compute_diff(diff_project, build_project)[0]
        self.package_diff[diff_key] = package_diff
        return package_diff

    def get_package_diff(
        self,
        request: osc.core.Request | None,
        config_inc: IncrementConfig,
        repo_sub_path: str,
        build_info: BuildInfo | None = None,
    ) -> defaultdict[str, set[Package]]:
        """Get the package diff for a configuration."""
        if config_inc.diff_project_suffix == "source-report":
            if not request:
                log.error("Source report diff requested but no request found")
                return defaultdict(set)
            return self.get_package_diff_from_source_report(request)

        if config_inc.diff_project_suffix != "none":
            return self.get_package_diff_from_repo(config_inc, repo_sub_path, build_info)

        return defaultdict(set)

    def make_scheduling_parameters(
        self, request: osc.core.Request | None, config_inc: IncrementConfig, build_info: BuildInfo
    ) -> ScheduleParams:
        """Prepare scheduling parameters for a build."""
        repo_sub_path = "/product"
        base_params = {
            "DISTRI": build_info.distri,
            "VERSION": build_info.version,
            "FLAVOR": build_info.flavor,
            "ARCH": build_info.arch,
            "BUILD": build_info.build,
            "INCREMENT_REPO": config_inc.build_project_url(config.settings.download_base_url) + repo_sub_path,
            **OBSOLETE_PARAMS,
        }
        IncrementApprover.populate_params_from_env(base_params, "CI_JOB_URL")
        base_params.update(config_inc.settings)
        extra_params = []
        if config_inc.diff_project_suffix != "none":
            package_diff = self.get_package_diff(request, config_inc, repo_sub_path, build_info)
            relevant_diff = package_diff[build_info.arch] | package_diff["noarch"]
            # schedule base params if package filter is empty for matching
            if IncrementApprover.match_packages(relevant_diff, config_inc.packages):
                extra_params.append({})
            # schedule additional builds based on changed packages
            extra_params.extend(self.extra_builds_for_additional_builds(relevant_diff, config_inc, build_info))
        else:
            # schedule always just base params if not computing the package diff
            extra_params.append({})
        return [merge_dicts(base_params, p) for p in extra_params]

    def schedule_openqa_jobs(self, build_info: BuildInfo, params: ScheduleParams) -> int:
        """Schedule jobs on openQA."""
        error_count = 0
        for p in params:
            suffix = f": {p}" if self.args.dry else ""
            log.info("Scheduling jobs for %s%s", build_info.string_with_params(p), suffix)
            if self.args.dry:
                continue
            try:
                self.client.post_job(p)
            except PostOpenQAError:
                error_count += 1
        return error_count

    def _handle_not_ready_jobs(
        self,
        build_info: BuildInfo,
        params: ScheduleParams,
        info_str: str,
        *,
        openqa_jobs_ready: bool | None,
        approval_status: ApprovalStatus,
    ) -> int:
        """Handle cases where openQA jobs are not ready or missing."""
        error_count = 0
        if openqa_jobs_ready is None:
            approval_status.reasons_to_disapprove.append("No jobs scheduled for " + info_str)
            if self.args.schedule:
                error_count += self.schedule_openqa_jobs(build_info, params)
        else:
            approval_status.reasons_to_disapprove.append("Not all jobs ready for " + info_str)
        return error_count

    def process_build_info(
        self,
        config_inc: IncrementConfig,
        build_info: BuildInfo,
        request: osc.core.Request,
        approval_status: ApprovalStatus,
    ) -> int:
        """Process a single build and update its approval status."""
        error_count = 0
        params = self.make_scheduling_parameters(request, config_inc, build_info)
        log.debug("Prepared scheduling parameters: %s", params)
        if len(params) < 1:
            log.info("Skipping %s for %s, filtered out via 'packages' or 'archs' setting", config_inc, build_info)
            return error_count

        info_str = "or".join([build_info.string_with_params(p) for p in params])
        log.debug("Requesting openQA job results for OBS request ID '%s' for %s", request.reqid, info_str)
        res = self.request_openqa_job_results(params, info_str)

        if self.args.reschedule:
            approval_status.reasons_to_disapprove.append("Re-scheduling jobs for " + info_str)
            return self.schedule_openqa_jobs(build_info, params)

        openqa_jobs_ready = self.check_openqa_jobs(res, build_info, params)
        if openqa_jobs_ready:
            approval_status.add(*(self.evaluate_list_of_openqa_job_results(res, request)))
        else:
            error_count += self._handle_not_ready_jobs(
                build_info,
                params,
                info_str,
                openqa_jobs_ready=openqa_jobs_ready,
                approval_status=approval_status,
            )

        return error_count

    def _get_approval_status(self, request: osc.core.Request) -> ApprovalStatus:
        """Get or create the approval status for an OBS request."""
        request_id = request.reqid
        if request_id in self.requests_to_approve:
            return self.requests_to_approve[request_id]

        status = ApprovalStatus(request, set(), [])
        self.requests_to_approve[request_id] = status
        return status

    def process_request_for_config(self, request: osc.core.Request | None, config_inc: IncrementConfig) -> int:
        """Process an OBS request for a specific configuration."""
        if request is None:
            return 0

        approval_status = self._get_approval_status(request)
        error_count = 0
        found_relevant_build = False
        for build_info in load_build_info(
            config_inc,
            config_inc.build_regex,
            config_inc.product_regex,
            config_inc.version_regex,
            self.get_regex_match,
        ):
            if len(config_inc.archs) > 0 and build_info.arch not in config_inc.archs:
                continue
            found_relevant_build = True
            error_count += self.process_build_info(config_inc, build_info, request, approval_status)

        if not found_relevant_build:
            approval_status.reasons_to_disapprove.append(
                f"No builds found for config {config_inc} in {config_inc.build_project()}"
            )
        return error_count

    def __call__(self) -> int:
        """Run the increment approval process."""
        error_count = 0
        for config_inc in self.config:
            request = find_request_on_obs(self.args, config_inc.build_project())
            error_count += self.process_request_for_config(request, config_inc)
        for request in self.requests_to_approve.values():
            error_count += self.handle_approval(request)
        return error_count
