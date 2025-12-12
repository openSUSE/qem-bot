# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
import re
import tempfile
from argparse import Namespace
from collections import defaultdict
from functools import cache
from logging import getLogger
from pprint import pformat
from typing import Any, NamedTuple

import osc.conf
import osc.core
from lxml import etree

from openqabot.config import DOWNLOAD_BASE, OBS_GROUP, OBS_URL, OBSOLETE_PARAMS
from openqabot.openqa import openQAInterface

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

    def string_with_params(self, params: dict[str, str]) -> str:
        version = params.get("VERSION", self.version)
        flavor = params.get("FLAVOR", self.flavor)
        arch = params.get("ARCH", self.arch)
        build = params.get("BUILD", self.build)
        return f"{self.product}v{version} build {build}@{arch} of flavor {flavor}"


class ApprovalStatus(NamedTuple):
    request: osc.core.Request
    ok_jobs: set[int] = set()  # noqa: RUF012 - Suggestion using ClassVar does not work; maybe a false positive.
    reasons_to_disapprove: list[str] = []  # noqa: RUF012 - Suggestion using ClassVar does not work; maybe a false positive.

    def add(self, ok_jobs: set[int], reasons_to_disapprove: list[str]) -> None:
        self.ok_jobs.update(ok_jobs)
        self.reasons_to_disapprove.extend(reasons_to_disapprove)


class IncrementApprover:
    def __init__(self, args: Namespace) -> None:
        self.args = args
        self.token = {"Authorization": f"Token {args.token}"}
        self.client = openQAInterface(args)
        self.package_diff = {}
        self.requests_to_approve = {}
        self.config = IncrementConfig.from_args(args)
        osc.conf.get_config(override_apiurl=OBS_URL)

    def _get_regex_match(self, pattern: str, string: str) -> re.Match | None:
        match = None
        try:
            match = re.search(pattern, string)
        except re.error:
            log.warning(
                "Pattern `%s` did not compile successfully. Considering as non-match and returning empty result.",
                pattern,
            )
        return match

    @cache
    def _find_request_on_obs(self, build_project: str) -> osc.core.Request | None:
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
            obs_requests = self._get_obs_request_list(project=build_project, req_state=tuple(relevant_states))
            filtered_requests = (
                request
                for request in sorted(obs_requests, reverse=True)
                for review in request.reviews
                if review.by_group == OBS_GROUP and review.state in relevant_states
            )
            relevant_request = next(filtered_requests, None)
        else:
            log.debug("Checking specified request %i", args.request_id)
            relevant_request = osc.core.Request.from_api(OBS_URL, str(args.request_id))
        if relevant_request is None:
            log.info("Skipping approval, no relevant requests in states %s", "/".join(relevant_states))
        else:
            log.debug("Found request %s", relevant_request.id)
            if hasattr(relevant_request.state, "to_xml"):
                log.debug(relevant_request.to_str())
        return relevant_request

    def _add_packages_for_action_project(
        self, action: osc.core.Action, project: str, repo: str, arch: str, packages: defaultdict[str, set[Package]]
    ) -> None:
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
            source_report = source_report_xml.getroot()
            for binary in source_report.iterfind("binary"):
                arch = binary.get("arch")
                packages[arch].add(Package(binary.get("name"), "", binary.get("version"), binary.get("release"), arch))
                packages["noarch"].add(Package(binary.get("package"), "", "", "", "noarch"))

    def _compute_packages_of_request_from_source_report(
        self, request: osc.core.Request | None
    ) -> tuple[defaultdict[str, set[Package]], int]:
        repo_a = defaultdict(set)
        repo_b = defaultdict(set)
        for action in request.actions:
            log.debug("Checking action '%s' -> '%s' of request %s", action.src_project, action.tgt_project, request.id)
            # add packages for target project (e.g. `SUSE:Products:SLE-Product-SLES:16.0:aarch64`), that is repo "A"
            self._add_packages_for_action_project(action, action.tgt_project, "images", "local", repo_a)
            # add packages for source project (e.g. `SUSE:SLFO:Products:SLES:16.0:TEST`), that is repo "B"
            self._add_packages_for_action_project(action, action.src_project, "product", "local", repo_b)
        return RepoDiff.compute_diff_for_packages("product repo", repo_a, "TEST repo", repo_b)

    @cache
    def _get_obs_request_list(self, project: str, req_state: tuple) -> list:
        return osc.core.get_request_list(OBS_URL, project=project, req_state=req_state)

    def _request_openqa_job_results(
        self,
        build_info: BuildInfo,
        params: list[dict[str, str]],
    ) -> list[dict[str, dict[str, dict[str, Any]]]]:
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
        results: list[dict[str, dict[str, dict[str, Any]]]],
        build_info: BuildInfo,
        params: list[dict[str, str]],
    ) -> bool | None:
        actual_states = set(results[0].keys()) if results else set()
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
        results: dict[str, dict[str, dict[str, Any]]],
        ok_jobs: set[int],
        not_ok_jobs: dict[str, set[str]],
    ) -> None:
        for state in final_states:
            for result, info in results.get(state, {}).items():
                if result in ok_results:
                    ok_jobs.update(set(info["job_ids"]))
                else:
                    not_ok_jobs[result].update(info["job_ids"])

    def _evaluate_list_of_openqa_job_results(
        self,
        list_of_results: list[dict[str, dict[str, dict[str, Any]]]],
    ) -> tuple[set[int], list[str]]:
        ok_jobs = set()  # keep track of ok jobs
        not_ok_jobs = defaultdict(set)  # keep track of not ok jobs
        openqa_url = self.client.url.geturl()
        for results in list_of_results:
            self._evaluate_openqa_job_results(results, ok_jobs, not_ok_jobs)
        reasons_to_disapprove = [
            f"The following openQA jobs ended up with result '{result}':\n"
            + "\n".join(f" - {openqa_url}/tests/{i}" for i in job_ids)
            for result, job_ids in not_ok_jobs.items()
        ]
        return (ok_jobs, reasons_to_disapprove)

    def _handle_approval(self, approval_status: ApprovalStatus) -> int:
        reasons_to_disapprove = approval_status.reasons_to_disapprove
        if len(reasons_to_disapprove) == 0:
            message = f"All {len(approval_status.ok_jobs)} jobs on openQA have {'/'.join(sorted(ok_results))}"
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

    def _determine_build_info(self, config: IncrementConfig) -> set[BuildInfo]:
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
            m = self._get_regex_match(config.build_regex, name)
            if not m:
                return None

            product = m.group("product")
            if not self._get_regex_match(config.build_regex, name):
                return None

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
                return BuildInfo(distri, product, version, flavor, arch, build)
            return None

        return {build_info for row in rows if (build_info := get_build_info_from_row(row))}

    def _extra_builds_for_package(
        self,
        package: Package,
        config: IncrementConfig,
        build_info: BuildInfo,
    ) -> dict[str, str] | None:
        for additional_build in config.additional_builds:
            package_name_regex = additional_build.get("package_name_regex", additional_build.get("regex"))
            if (package_name_match := self._get_regex_match(package_name_regex, package.name)) is None:
                continue
            package_version_regex = additional_build.get("package_version_regex")
            if package_version_regex is not None and not self._get_regex_match(package_version_regex, package.version):
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
        package_diff: set[Package],
        config: IncrementConfig,
        build_info: BuildInfo,
    ) -> list[dict[str, str]]:
        def handle_package(p: Package) -> dict[str, str] | None:
            return self._extra_builds_for_package(p, config, build_info)

        extra_builds = map(handle_package, package_diff)
        return [*filter(lambda b: b is not None, extra_builds)]

    @staticmethod
    def _populate_params_from_env(params: dict[str, str], env_var: str) -> None:
        value = os.environ.get(env_var, "")
        if len(value) > 0:
            params["__" + env_var] = value

    @staticmethod
    def _match_packages(package_diff: set[Package], packages_to_find: list[str]) -> bool:
        if len(packages_to_find) == 0:
            return True
        names_of_changed_packages = {p.name for p in package_diff}
        return any(package in names_of_changed_packages for package in packages_to_find)

    def _package_diff(
        self, request: osc.core.Request | None, config: IncrementConfig, repo_sub_path: str
    ) -> defaultdict[str, set[Package]]:
        package_diff = defaultdict(set)
        if config.diff_project_suffix == "source-report":
            # compute diff by checking the source report on obs
            diff_key = "request:" + str(request.id)
            package_diff = self.package_diff.get(diff_key)
            if package_diff is None:
                log.debug("Computing source report diff for request %s", request.id)
                package_diff = self._compute_packages_of_request_from_source_report(request)[0]
                log.debug("Packages updated by request %s: %s", request.id, pformat(package_diff))
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

    def _make_scheduling_parameters(
        self, request: osc.core.Request | None, config: IncrementConfig, build_info: BuildInfo
    ) -> list[dict[str, str]]:
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
        IncrementApprover._populate_params_from_env(base_params, "CI_JOB_URL")
        base_params.update(config.settings)
        extra_params = []
        if config.diff_project_suffix != "none":
            package_diff = self._package_diff(request, config, repo_sub_path)
            relevant_diff = package_diff[build_info.arch] | package_diff["noarch"]
            # schedule base params if package filter is empty for matching
            if IncrementApprover._match_packages(relevant_diff, config.packages):
                extra_params.append({})
            # schedule additional builds based on changed packages
            extra_params.extend(self._extra_builds_for_additional_builds(relevant_diff, config, build_info))
        else:
            # schedule always just base params if not computing the package diff
            extra_params.append({})
        return [*(merge_dicts(base_params, p) for p in extra_params)]

    def _schedule_openqa_jobs(self, build_info: BuildInfo, params: list[dict[str, str]]) -> int:
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

    def _process_request_for_config(self, request: osc.core.Request | None, config: IncrementConfig) -> int:
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
            params = self._make_scheduling_parameters(request, config, build_info)
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
            request = self._find_request_on_obs(config.build_project())
            error_count += self._process_request_for_config(request, config)
        for request in self.requests_to_approve.values():
            error_count += self._handle_approval(request)
        return error_count
