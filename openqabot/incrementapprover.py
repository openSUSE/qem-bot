# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Increment Approver."""

from __future__ import annotations

import os
import re
import tempfile
from collections import defaultdict
from functools import cache, lru_cache
from itertools import chain
from logging import getLogger
from pprint import pformat
from typing import TYPE_CHECKING, Any, NamedTuple, cast

import osc.conf
import osc.core
from lxml import etree  # type: ignore[unresolved-import]

from openqabot.config import DOWNLOAD_BASE, OBS_GROUP, OBS_URL, OBSOLETE_PARAMS
from openqabot.openqa import OpenQAInterface

from .errors import PostOpenQAError
from .loader.incrementconfig import IncrementConfig
from .repodiff import Package, RepoDiff
from .utils import merge_dicts
from .utils import retry10 as retried_requests

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


class BuildInfo(NamedTuple):
    """Information about a build."""

    distri: str
    product: str
    version: str
    flavor: str
    arch: str
    build: str

    def __str__(self) -> str:
        """Return a string representation of the BuildInfo."""
        return f"{self.product}v{self.version} build {self.build}@{self.arch} of flavor {self.flavor}"

    def string_with_params(self, params: dict[str, str]) -> str:
        """Return a string representation of the build with overridden parameters."""
        version = params.get("VERSION", self.version)
        flavor = params.get("FLAVOR", self.flavor)
        arch = params.get("ARCH", self.arch)
        build = params.get("BUILD", self.build)
        return f"{self.product}v{version} build {build}@{arch} of flavor {flavor}"


class ApprovalStatus(NamedTuple):
    """Status of an approval request."""

    request: osc.core.Request
    ok_jobs: set[int]
    reasons_to_disapprove: list[str]

    @classmethod
    def create(cls, request: osc.core.Request) -> ApprovalStatus:
        """Create a new ApprovalStatus instance."""
        return cls(request, set(), [])

    def add(self, ok_jobs: set[int], reasons_to_disapprove: list[str]) -> None:
        """Add jobs and reasons to the status."""
        self.ok_jobs.update(ok_jobs)
        self.reasons_to_disapprove.extend(reasons_to_disapprove)


class IncrementApprover:
    """Logic for approving product increments."""

    def __init__(self, args: Namespace) -> None:
        """Initialize the IncrementApprover class."""
        self.args = args
        self.token = {"Authorization": f"Token {args.token}"}
        self.client = OpenQAInterface(args)
        self.package_diff = {}
        self.requests_to_approve = {}
        self.config = IncrementConfig.from_args(args)
        osc.conf.get_config(override_apiurl=OBS_URL)

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

    @cache  # noqa: B019
    def find_request_on_obs(self, build_project: str) -> osc.core.Request | None:
        """Find a relevant product increment request on OBS."""
        args = self.args
        relevant_states = ["new", "review"]
        if args.accepted:
            relevant_states.append("accepted")
        if args.request_id is None:
            log.debug(
                "Checking for product increment requests to be reviewed by %s on %s",
                OBS_GROUP,
                build_project,
            )
            obs_requests = self.get_obs_request_list(project=build_project, req_state=tuple(relevant_states))
            filtered_requests = (
                request
                for request in sorted(obs_requests, reverse=True)
                for review in request.reviews
                if review.by_group == OBS_GROUP and review.state in relevant_states
            )
            relevant_request = next(filtered_requests, None)
        else:
            log.debug("Checking specified request %i", args.request_id)
            relevant_request = osc.core.Request.from_api(OBS_URL, args.request_id)
        if relevant_request is None:
            states_str = "/".join(relevant_states)
            log.info("Skipping approval: %s: No relevant requests in states %s", build_project, states_str)
        else:
            log.info("Found product increment request on %s: %s", build_project, relevant_request.id)
            if hasattr(relevant_request.state, "to_xml"):
                log.debug(relevant_request.to_str())
        return relevant_request

    def add_packages_for_action_project(  # noqa: PLR6301
        self,
        action: Any,  # noqa: ANN401
        project: str,
        repo: str,
        arch: str,
        packages: defaultdict[str, set[Package]],
    ) -> None:
        """Add packages from source reports of a project to the packages dictionary."""
        log.debug(
            "Finding source reports for package %s in project %s for repo/arch %s/%s",
            action.src_package,
            project,
            repo,
            arch,
        )
        repos = osc.core.get_repos_of_project(OBS_URL, prj=project)
        binaries = [
            osc.core.get_binarylist(OBS_URL, prj=project, repo=repo.name, arch=repo.arch, package=action.src_package)
            for repo in repos
        ]
        source_reports = [b for binary_list in binaries for b in binary_list if b.endswith("Source.report")]
        for source_report in source_reports:
            log.debug("Processing source report %s for %s and %s/%s", source_report, project, repo, arch)
            with tempfile.TemporaryDirectory() as tmpdirname:
                source_report_xml_path = f"{tmpdirname}/source-report-{project}-{repo}-{arch}.xml"
                osc.core.get_binary_file(
                    OBS_URL,
                    prj=project,
                    package=action.src_package,
                    repo=repo,
                    arch=arch,
                    filename=source_report,
                    target_filename=source_report_xml_path,
                )
                source_report_xml = etree.parse(source_report_xml_path)
            source_report_root = source_report_xml.getroot()
            for binary in source_report_root.iterfind("binary"):
                arch = binary.get("arch")
                packages[arch].add(Package(binary.get("name"), "", binary.get("version"), binary.get("release"), arch))
                packages["noarch"].add(Package(binary.get("package"), "", "", "", "noarch"))

    def compute_packages_of_request_from_source_report(
        self, request: osc.core.Request
    ) -> tuple[defaultdict[str, set[Package]], int]:
        """Compute the package diff of a request based on source reports."""
        repo_a = defaultdict(set)
        repo_b = defaultdict(set)
        for action in request.actions:
            log.debug("Checking action '%s' -> '%s' of request %s", action.src_project, action.tgt_project, request.id)
            # add packages for target project (e.g. `SUSE:Products:SLE-Product-SLES:16.0:aarch64`), that is repo "A"
            self.add_packages_for_action_project(action, action.tgt_project, "images", "local", repo_a)
            # add packages for source project (e.g. `SUSE:SLFO:Products:SLES:16.0:TEST`), that is repo "B"
            self.add_packages_for_action_project(action, action.src_project, "product", "local", repo_b)
        return RepoDiff.compute_diff_for_packages("product repo", repo_a, "TEST repo", repo_b)

    @staticmethod
    @cache
    def get_obs_request_list(project: str, req_state: tuple) -> list:
        """Get a list of requests from OBS."""
        return osc.core.get_request_list(OBS_URL, project, req_state=req_state)

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

    def check_openqa_jobs(self, results: OpenQAResults, build_info: BuildInfo, params: ScheduleParams) -> bool | None:  # noqa: PLR6301
        """Check if all openQA jobs are finished."""
        actual_states = {state for result in results for state in result}
        pending_states = actual_states - final_states
        if len(actual_states) == 0:
            log.info(
                "Skipping approval: There are no relevant jobs on openQA for %s",
                (" or ".join([build_info.string_with_params(param) for param in params]) if len(params) > 0 else {}),
            )
            return None
        if len(pending_states):
            log.info(
                "Skipping approval: Some jobs on openQA for %s are in pending states (%s)",
                build_info,
                ", ".join(sorted(pending_states)),
            )
            return False
        return True

    def evaluate_openqa_job_results(  # noqa: PLR6301
        self,
        results: OpenQAResult,
        ok_jobs: set[int],
        not_ok_jobs: dict[str, set[str]],
    ) -> None:
        """Evaluate openQA job results and sort them into ok and not_ok sets."""
        all_items = chain.from_iterable(results.get(s, {}).items() for s in final_states)
        for result, info in all_items:
            destination = ok_jobs if result in ok_results else not_ok_jobs[result]
            destination.update(info["job_ids"])

    def evaluate_list_of_openqa_job_results(self, list_of_results: OpenQAResults) -> tuple[set[int], list[str]]:
        """Evaluate a list of openQA job results."""
        ok_jobs = set()  # keep track of ok jobs
        not_ok_jobs = defaultdict(set)  # keep track of not ok jobs
        openqa_url = self.client.url.geturl()
        for results in list_of_results:
            self.evaluate_openqa_job_results(results, ok_jobs, not_ok_jobs)
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
        osc.core.change_review_state(apiurl=OBS_URL, reqid=reqid, newstate="accepted", by_group=OBS_GROUP, message=msg)

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

    def determine_build_info(self, config: IncrementConfig) -> set[BuildInfo]:
        """Determine build information from the project's repository listing."""
        # deduce DISTRI, VERSION, FLAVOR, ARCH and BUILD from the spdx files in the repo listing similar to the sync
        # plugin
        build_project_url = config.build_project_url()
        sub_path = config.build_listing_sub_path
        url = f"{build_project_url}/{sub_path}/?jsontable=1"
        log.debug("Checking for '%s' files on %s", config.build_regex, url)
        rows = retried_requests.get(url).json().get("data", [])

        def get_build_info_from_row(row: dict[str, Any]) -> BuildInfo | None:
            name = row.get("name", "")
            log.debug("Found file: %s", name)
            m = self.get_regex_match(config.build_regex, name)
            if not m:
                return None

            product = m.group("product")
            if not self.get_regex_match(config.product_regex, product):
                return None

            distri = config.distri
            version = m.group("version")
            if not self.get_regex_match(config.version_regex, version):
                log.info("Skipping version string '%s' not matching version regex '%s'", version, config.version_regex)
                return None
            arch = m.group("arch")
            build = m.group("build")
            try:
                flavor = m.group("flavor")
            except IndexError:
                flavor = default_flavor
            flavor = f"{flavor}-{config.flavor_suffix}"

            if (
                config.distri in {"any", distri}
                and config.flavor in {"any", flavor}
                and config.version in {"any", version}
            ):
                return BuildInfo(distri, product, version, flavor, arch, build)
            return None

        return {build_info for row in rows if (build_info := get_build_info_from_row(row))}

    def extra_builds_for_package(
        self,
        package: Package,
        config: IncrementConfig,
        build_info: BuildInfo,
    ) -> dict[str, str] | None:
        """Determine extra build parameters for a specific package."""
        for additional_build in config.additional_builds:
            package_name_regex = additional_build.get("package_name_regex") or additional_build.get("regex", "")
            if (package_name_match := self.get_regex_match(package_name_regex, package.name)) is None:
                continue
            package_version_regex = additional_build.get("package_version_regex")
            if package_version_regex is not None and not self.get_regex_match(package_version_regex, package.version):
                continue
            extra_build = [build_info.build, additional_build["build_suffix"]]
            extra_params: dict[str, str] = {}
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
            extra_params.update(cast("dict[str, str]", additional_build["settings"]))
            return extra_params
        return None

    def extra_builds_for_additional_builds(
        self,
        package_diff: set[Package],
        config: IncrementConfig,
        build_info: BuildInfo,
    ) -> list[dict[str, str]]:
        """Determine extra builds for all additional builds in the configuration."""

        def handle_package(p: Package) -> dict[str, str] | None:
            return self.extra_builds_for_package(p, config, build_info)

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

    def get_package_diff(
        self, request: osc.core.Request | None, config: IncrementConfig, repo_sub_path: str
    ) -> defaultdict[str, set[Package]]:
        """Get the package diff for a configuration."""
        package_diff = defaultdict(set)
        diff_key = None
        if config.diff_project_suffix == "source-report":
            # compute diff by checking the source report on obs
            if not request:
                log.error("Source report diff requested but no request found")
                return package_diff
            diff_key = "request:" + str(request.id)
            package_diff = self.package_diff.get(diff_key)
            if package_diff is None:
                log.info("Computing source report diff for OBS request ID %s", request.id)
                package_diff = self.compute_packages_of_request_from_source_report(request)[0]
                log.debug("Packages updated by OBS request ID %s: %s", request.id, pformat(package_diff))
        elif config.diff_project_suffix != "none":
            # compute diff by comparing repositories if "diff_project_suffix" is configured
            build_project = config.build_project() + repo_sub_path
            diff_project = config.diff_project()
            diff_key = f"{build_project}:{diff_project}"
            package_diff = self.package_diff.get(diff_key)
            if package_diff is None:
                log.debug("Comuting repo diff to project %s", diff_project)
                package_diff = RepoDiff(self.args).compute_diff(diff_project, build_project)[0]
        if diff_key:
            self.package_diff[diff_key] = package_diff
        return package_diff

    def make_scheduling_parameters(
        self, request: osc.core.Request | None, config: IncrementConfig, build_info: BuildInfo
    ) -> ScheduleParams:
        """Prepare scheduling parameters for a build."""
        repo_sub_path = "/product"
        base_params = {
            "DISTRI": build_info.distri,
            "VERSION": build_info.version,
            "FLAVOR": build_info.flavor,
            "ARCH": build_info.arch,
            "BUILD": build_info.build,
            "INCREMENT_REPO": config.build_project_url(DOWNLOAD_BASE) + repo_sub_path,
            **OBSOLETE_PARAMS,
        }
        IncrementApprover.populate_params_from_env(base_params, "CI_JOB_URL")
        base_params.update(config.settings)
        extra_params = []
        if config.diff_project_suffix != "none":
            package_diff = self.get_package_diff(request, config, repo_sub_path)
            relevant_diff = package_diff[build_info.arch] | package_diff["noarch"]
            # schedule base params if package filter is empty for matching
            if IncrementApprover.match_packages(relevant_diff, config.packages):
                extra_params.append({})
            # schedule additional builds based on changed packages
            extra_params.extend(self.extra_builds_for_additional_builds(relevant_diff, config, build_info))
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

    def process_build_info(
        self,
        config: IncrementConfig,
        build_info: BuildInfo,
        request: osc.core.Request,
        approval_status: ApprovalStatus,
    ) -> int:
        """Process a single build and update its approval status."""
        error_count = 0
        params = self.make_scheduling_parameters(request, config, build_info)
        log.debug("Prepared scheduling parameters: %s", params)
        if len(params) < 1:
            log.info("Skipping %s for %s, filtered out via 'packages' or 'archs' setting", config, build_info)
            return error_count

        info_str = "or".join([build_info.string_with_params(p) for p in params])
        log.debug("Requesting openQA job results for OBS request ID '%s' for %s", request.reqid, info_str)
        res = self.request_openqa_job_results(params, info_str)

        if self.args.reschedule:
            approval_status.reasons_to_disapprove.append("Re-scheduling jobs for " + info_str)
            error_count += self.schedule_openqa_jobs(build_info, params)
            return error_count

        openqa_jobs_ready = self.check_openqa_jobs(res, build_info, params)
        if openqa_jobs_ready is None:
            approval_status.reasons_to_disapprove.append("No jobs scheduled for " + info_str)
            if self.args.schedule:
                error_count += self.schedule_openqa_jobs(build_info, params)
        elif openqa_jobs_ready:
            approval_status.add(*(self.evaluate_list_of_openqa_job_results(res)))
        else:
            approval_status.reasons_to_disapprove.append("Not all jobs ready for " + info_str)

        return error_count

    def process_request_for_config(self, request: osc.core.Request | None, config: IncrementConfig) -> int:
        """Process an OBS request for a specific configuration."""
        error_count = 0
        if request is None:
            return error_count

        request_id = request.reqid
        if request_id in self.requests_to_approve:
            approval_status = self.requests_to_approve[request_id]
        else:
            approval_status = ApprovalStatus.create(request)
            self.requests_to_approve[request_id] = approval_status

        found_relevant_build = False
        for build_info in self.determine_build_info(config):
            if len(config.archs) > 0 and build_info.arch not in config.archs:
                continue
            found_relevant_build = True
            error_count += self.process_build_info(config, build_info, request, approval_status)

        if not found_relevant_build:
            approval_status.reasons_to_disapprove.append(
                f"No builds found for config {config} in {config.build_project()}"
            )
        return error_count

    def __call__(self) -> int:
        """Run the increment approval process."""
        error_count = 0
        for config in self.config:
            request = self.find_request_on_obs(config.build_project())
            error_count += self.process_request_for_config(request, config)
        for request in self.requests_to_approve.values():
            error_count += self.handle_approval(request)
        return error_count
