# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Increment Approver."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from itertools import chain
from logging import getLogger
from pprint import pformat
from typing import TYPE_CHECKING, Any

import osc.conf
import osc.core

from openqabot import config
from openqabot.config import OBSOLETE_PARAMS
from openqabot.openqa import OpenQAInterface
from openqabot.pc_helper import apply_public_cloud_settings

from .commenter import Commenter
from .errors import AmbiguousApprovalStatusError, PostOpenQAError
from .loader.buildinfo import load_build_info
from .loader.incrementconfig import IncrementConfig
from .loader.sourcereport import compute_packages_of_request_from_source_report
from .repodiff import Package, RepoDiff
from .requests import find_request_on_obs
from .types.increment import ApprovalStatus, BuildIdentifier, BuildInfo
from .utils import merge_dicts, unique_dicts

if TYPE_CHECKING:
    from argparse import Namespace

log = getLogger("bot.increment_approver")
ok_results = {"passed", "softfailed"}
final_states = {"done", "cancelled"}

OpenQAResult = dict[str, dict[str, dict[str, Any]]]
OpenQAResults = list[OpenQAResult]
ScheduleParams = list[dict[str, str]]


class IncrementApprover:
    """Logic for approving product increments.

    This class handles the verification of product increment requests on OBS/IBS.
    It fetches test results from openQA based on scheduling parameters,
    filters out development jobs, and decides whether to approve or
    disapprove the request.
    """

    def __init__(self, args: Namespace) -> None:
        """Initialize the IncrementApprover class."""
        self.args = args
        self.client = OpenQAInterface()
        self.package_diff = {}
        self.requests_to_approve = {}
        # safeguard us from using same job ID for 2 requests
        self.unique_jobid_request_pair = {}
        self.config = IncrementConfig.from_args(args)
        self.comment = getattr(args, "comment", False)

        self.commenter = Commenter(args, submissions=[])
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
                msg = (
                    f"Job ID {jobid} already used for request "
                    f"{self.unique_jobid_request_pair[jobid]}, but now requested for {request.reqid}"
                )
                raise AmbiguousApprovalStatusError(msg)

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

    def _filter_jobs(self, jobs: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Filter jobs within a state, removing those in devel groups."""
        return {name: info for name, info in jobs.items() if not self.client.is_in_devel_group(info)}

    def _filter_results(self, results: OpenQAResults) -> OpenQAResults:
        """Remove jobs belonging to development groups from openQA results."""
        return [{s: f for s, j in res.items() if (f := self._filter_jobs(j))} for res in results]

    @staticmethod
    def _enrich_job_info(info: dict[str, Any], job_map: dict[int, dict[str, Any]]) -> dict[str, Any]:
        """Enrich job information with metadata from the first job ID."""
        if not (ids := info.get("job_ids")) or not (job := job_map.get(int(ids[0]))):
            return info

        return info | {
            "group": job.get("group"),
            "group_id": job.get("group_id"),
            "distri": job.get("distri"),
            "version": job.get("version"),
            "build": job.get("build"),
        }

    @staticmethod
    def _enrich_stats(stat: OpenQAResult, job_map: dict[int, dict[str, Any]]) -> OpenQAResult:
        """Enrich all jobs in a scheduled product result with metadata."""
        return {
            status: {name: IncrementApprover._enrich_job_info(info, job_map) for name, info in jobs.items()}
            for status, jobs in stat.items()
        }

    def request_openqa_job_results(self, params: ScheduleParams, info_str: str) -> OpenQAResults:
        """Fetch results from openQA for the specified scheduling parameters."""
        log.debug("Checking openQA job results for %s", info_str)

        def fetch_stats(p: dict[str, Any]) -> OpenQAResult:
            return self.client.get_scheduled_product_stats({
                "distri": p["DISTRI"],
                "version": p["VERSION"],
                "flavor": p["FLAVOR"],
                "arch": p["ARCH"],
                "build": p["BUILD"],
                "product": p.get("PRODUCT"),
            })

        with ThreadPoolExecutor() as executor:
            stats = list(executor.map(fetch_stats, params))

        # Fetch all relevant job details in a single API call to avoid N+1 query problem
        job_ids = [
            int(ids[0])
            for stat in stats
            for jobs in stat.values()
            for info in jobs.values()
            if (ids := info.get("job_ids"))
        ]
        job_map = {job["id"]: job for job in self.client.get_jobs_by_ids(job_ids)}

        res = [IncrementApprover._enrich_stats(stat, job_map) for stat in stats]

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
        self,
        results: OpenQAResult,
        ok_jobs: set[int],
        not_ok_jobs: dict[str, set[str]],
        jobs: list[dict[str, Any]],
        request: osc.core.Request,
    ) -> None:
        """Evaluate openQA job results and sort them into ok and not_ok sets."""
        for result, info in chain.from_iterable(results.get(s, {}).items() for s in final_states):
            ids = info["job_ids"]
            common = {k: info.get(k) for k in ("group_id", "build", "distri", "version")}
            jobs.extend({**common, "id": j, "status": result} for j in ids)
            (ok_jobs if result in ok_results else not_ok_jobs[result]).update(ids)
            self.check_unique_jobid_request_pair(ids, request)

    def evaluate_list_of_openqa_job_results(
        self, list_of_results: OpenQAResults, request: osc.core.Request
    ) -> tuple[set[int], list[str], list[dict[str, Any]]]:
        """Evaluate a list of openQA job results."""
        ok_jobs = set()  # keep track of ok jobs
        not_ok_jobs = defaultdict(set)  # keep track of not ok jobs
        jobs: list[dict[str, Any]] = []
        openqa_url = self.client.url.geturl()
        for results in list_of_results:
            self.evaluate_openqa_job_results(results, ok_jobs, not_ok_jobs, jobs, request)
        reasons_to_disapprove = [
            f"The following openQA jobs ended up with result '{result}':\n"
            + "\n".join(f" - {openqa_url}/tests/{i}" for i in job_ids)
            for result, job_ids in not_ok_jobs.items()
        ]
        return (ok_jobs, reasons_to_disapprove, jobs)

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
        id_msg = f"OBS request {config.settings.obs_web_url}/request/show/{reqid}"

        # Safeguard: only block if NO jobs were ever identified for this request.
        # If processed_jobs is set but ok_jobs is empty, it means all jobs were filtered
        # (e.g. development groups) and approval should proceed if there are no other blockers.
        if not reasons_to_disapprove and not approval_status.ok_jobs and not approval_status.processed_jobs:
            reasons_to_disapprove.append("No openQA jobs were found/checked for this request.")

        if self.comment and approval_status.builds:
            state = "passed" if not reasons_to_disapprove else "failed"
            msg = self.commenter.summarize_message(approval_status.builds, approval_status.jobs)
            self.commenter.osc_comment_on_request(str(reqid), msg, state)

        if not reasons_to_disapprove:
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
        if (archs := additional_build.get("archs")) and package.arch not in archs:
            return None

        if not (match := self._match_package_name_and_version(package, additional_build)):
            return None

        groups = match.groupdict()
        kernel_version = (groups.get("kernel_version") or "").replace("_", ".")

        build_parts = [
            f"PI-{build_info.build}",
            additional_build["build_suffix"],
            groups.get("kind"),
            kernel_version,
        ]

        params = {"BUILD": "-".join(filter(None, build_parts))}
        if kernel_version:
            params["KERNEL_VERSION"] = kernel_version

        return params | additional_build["settings"]

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

    @staticmethod
    def _is_initial_version(package: Package) -> bool:
        return bool(package.version and re.match(r"^1(?:\..*)?$", package.version))

    @staticmethod
    def _is_placeholder(package: Package) -> bool:
        return not package.version

    @staticmethod
    def _is_debug_asset(package: Package) -> bool:
        return "debug" in package.name or package.arch in {"src", "nosrc"}

    def extra_builds_for_package(
        self,
        package: Package,
        config_inc: IncrementConfig,
        build_info: BuildInfo,
    ) -> dict[str, str] | None:
        """Determine extra build parameters for a specific package."""
        if self._is_placeholder(package) or self._is_initial_version(package) or self._is_debug_asset(package):
            return None

        return next(
            (
                res
                for additional_build in config_inc.additional_builds
                if (res := self._match_additional_build(package, additional_build, build_info)) is not None
            ),
            None,
        )

    def extra_builds_for_additional_builds(
        self,
        package_diff: set[Package],
        config_inc: IncrementConfig,
        build_info: BuildInfo,
    ) -> list[dict[str, str]]:
        """Determine extra builds for all additional builds in the configuration."""
        return [b for p in package_diff if (b := self.extra_builds_for_package(p, config_inc, build_info)) is not None]

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
        diff_key = "request:" + str(request.reqid)
        package_diff = self.package_diff.get(diff_key)
        if package_diff is None:
            id_url = f"{config.settings.obs_web_url}/request/show/{request.reqid}"
            log.info("Computing source report diff for OBS request %s", id_url)
            package_diff = compute_packages_of_request_from_source_report(request)[0]
            log.debug("Packages updated by OBS request %s: %s", id_url, pformat(package_diff))
            self.package_diff[diff_key] = package_diff
        return package_diff

    def get_package_diff_from_repo(
        self, config_inc: IncrementConfig, repo_sub_path: str, build_info: BuildInfo | None = None
    ) -> defaultdict[str, set[Package]]:
        """Compute package diff by comparing repositories."""
        build_project = config_inc.build_project() + repo_sub_path

        is_reference_repo = False
        diff_project = config_inc.diff_project()
        if build_info and build_info.flavor in config_inc.reference_repos:
            is_reference_repo = True
            diff_project = config_inc.reference_repos[build_info.flavor]

            channel = build_info.flavor.removesuffix(f"-{config_inc.flavor_suffix}")
            params = {
                "base": "",
                "project": config_inc.build_project(),
                "version": build_info.version,
                "arch": build_info.arch,
                "channel": channel,
                "suffix": config_inc.diff_project_suffix,
                "product": build_info.product,
            }
            build_project = (
                config_inc.build_repo_template.format(**(params | {"base": build_project}))
                if config_inc.build_repo_template
                else f"{build_project}/{channel}/{build_info.arch}"
            )
            diff_project = (
                config_inc.diff_repo_template.format(**(params | {"base": diff_project}))
                if config_inc.diff_repo_template
                else f"{diff_project}/{build_info.version}/{config_inc.diff_project_suffix}/{build_info.arch}"
            )

        if not is_reference_repo and any(s in diff_project for s in ("-Debug", "-Source")):
            log.debug("Skipping repo diffing for %s (contains -Debug or -Source)", diff_project)
            return defaultdict(set)

        diff_key = f"{build_project}:{diff_project}"
        if diff_key in self.package_diff:
            return self.package_diff[diff_key]

        log.debug("Computing repo diff to project %s", diff_project)
        self.package_diff[diff_key] = RepoDiff(self.args).compute_diff(diff_project, build_project)[0]
        return self.package_diff[diff_key]

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
            "BUILD": f"PI-{build_info.build}",
            "PRODUCT": build_info.product,
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
        return unique_dicts([merge_dicts(base_params, p) for p in extra_params])

    def schedule_openqa_jobs(self, build_info: BuildInfo, params: ScheduleParams) -> int:
        """Schedule jobs on openQA."""
        error_count = 0
        for p in params:
            settings = apply_public_cloud_settings(p.copy()) or p
            log.info(
                "Scheduling jobs for %s%s", build_info.string_with_params(settings), f": {p}" if self.args.dry else ""
            )
            try:
                self.client.post_job(settings)
            except PostOpenQAError:
                error_count += 1
        return error_count

    def _handle_not_ready_jobs(
        self,
        build_info: BuildInfo,
        params: ScheduleParams,
        *,
        openqa_jobs_ready: bool | None,
        approval_status: ApprovalStatus,
        jobs_were_filtered: bool = False,
    ) -> int:
        """Manage disapproval reasons and optional rescheduling for incomplete openQA results.

        Args:
            build_info (BuildInfo): Metadata regarding the product and build version.
            params (ScheduleParams): The parameters required to identify or schedule openQA jobs.
            openqa_jobs_ready (bool | None): Job state (None for missing, False for pending).
            approval_status (ApprovalStatus): The status container updated with disapproval reasons.
            jobs_were_filtered (bool): Controls if some jobs were filtered which would mean that we
                should exclude them from approval status.

        Returns:
            int: The number of failed job postings if rescheduling is performed; otherwise 0.

        """
        info_str = build_info.format_multi_build(params)
        if openqa_jobs_ready is False:
            approval_status.reasons_to_disapprove.append(f"Not all jobs ready for {info_str}")
            return 0

        if jobs_were_filtered:
            log.info("All jobs filtered for %s (development groups ignored)", info_str)
            return 0

        approval_status.reasons_to_disapprove.append(f"No jobs scheduled for {info_str}")
        return self.schedule_openqa_jobs(build_info, params) if self.args.schedule else 0

    def process_build_info(
        self,
        config_inc: IncrementConfig,
        build_info: BuildInfo,
        request: osc.core.Request,
        approval_status: ApprovalStatus,
    ) -> int:
        """Process a single build and update its approval status."""
        params = self.make_scheduling_parameters(request, config_inc, build_info)

        if not params:
            log.info("Skipping %s for %s, filtered out via 'packages' or 'archs' setting", config_inc, build_info)
            return 0

        def _k(p: dict[str, str]) -> tuple[str, str, str, str, str, str]:
            return p["DISTRI"], p["VERSION"], p["FLAVOR"], p["ARCH"], p["BUILD"], p.get("PRODUCT", "")

        params = [p for p in params if _k(p) not in approval_status.processed_jobs]
        for p in params:
            approval_status.processed_jobs.add(_k(p))

        if not params:
            return 0

        info_str = build_info.format_multi_build(params)
        log.debug(
            "Prepared scheduling parameters: %s\nRequesting openQA job results for "
            "OBS request %s/request/show/%s for %s",
            params,
            config.settings.obs_web_url,
            request.reqid,
            info_str,
        )
        unfiltered_results = self.request_openqa_job_results(params, info_str)
        filtered_results = self._filter_results(unfiltered_results)

        if self.args.reschedule:
            approval_status.reasons_to_disapprove.append(f"Re-scheduling jobs for {info_str}")
            return self.schedule_openqa_jobs(build_info, params)

        openqa_jobs_ready = self.check_openqa_jobs(filtered_results, build_info, params)
        if openqa_jobs_ready:
            ok_jobs, reasons, jobs = self.evaluate_list_of_openqa_job_results(filtered_results, request)
            builds = {BuildIdentifier.from_params(p) for p in params if "BUILD" in p}
            approval_status.add(ok_jobs, reasons, builds, jobs)
            return 0

        return self._handle_not_ready_jobs(
            build_info,
            params,
            openqa_jobs_ready=openqa_jobs_ready,
            approval_status=approval_status,
            jobs_were_filtered=unfiltered_results != filtered_results,
        )

    def _get_approval_status(self, request: osc.core.Request) -> ApprovalStatus:
        """Get or create the approval status for an OBS request."""
        request_id = request.reqid
        if request_id in self.requests_to_approve:
            return self.requests_to_approve[request_id]

        status = ApprovalStatus(request, set(), [], set(), set(), [])
        self.requests_to_approve[request_id] = status
        return status

    def process_request_for_config(
        self, request: osc.core.Request | None, config_inc: IncrementConfig, build_infos: set[BuildInfo]
    ) -> int:
        """Process an OBS request for a specific configuration."""
        if request is None:
            return 0

        approval_status = self._get_approval_status(request)
        error_count = 0
        found_relevant_build = False
        for build_info in build_infos:
            if not all(
                getattr(config_inc, k) in {"any", getattr(build_info, k)}
                for k in ("distri", "flavor", "version", "arch")
            ):
                continue
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
        single_request = (
            osc.core.Request.from_api(config.settings.obs_url, self.args.request_id) if self.args.request_id else None
        )

        grouped_configs: dict[tuple, list[IncrementConfig]] = defaultdict(list)
        for config_inc in self.config:
            if single_request and single_request.actions[0].src_project != config_inc.build_project():
                log.debug(
                    "Skipping config %s as it does not match request %s project %s",
                    config_inc.build_project(),
                    self.args.request_id,
                    single_request.actions[0].src_project,
                )
                continue
            grouped_configs[config_inc.group_key].append(config_inc)

        for configs in grouped_configs.values():
            rep_config = configs[0]
            build_infos = load_build_info(
                rep_config,
                rep_config.build_regex,
                rep_config.product_regex,
                rep_config.version_regex,
                self.get_regex_match,
            )
            for config_inc in configs:
                request = find_request_on_obs(self.args, config_inc.build_project())
                error_count += self.process_request_for_config(request, config_inc, build_infos)

        for request in self.requests_to_approve.values():
            error_count += self.handle_approval(request)
        return error_count
