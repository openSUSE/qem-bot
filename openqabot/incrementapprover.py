# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from collections import defaultdict
from typing import Any, Dict, List, Tuple, Optional, Set, NamedTuple
import re
from logging import getLogger
from pathlib import Path
from pprint import pformat

from ruamel.yaml import YAML  # type: ignore

import osc.conf
import osc.core

from openqabot.openqa import openQAInterface

from .errors import PostOpenQAError
from .repodiff import Package, RepoDiff
from .utils import retry10 as requests, merge_dicts
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


class IncrementConfig(NamedTuple):
    distri: str
    version: str
    flavor: str
    project_base: str
    build_project_suffix: str
    diff_project_suffix: str
    build_listing_sub_path: str
    build_regex: str
    product_regex: str

    def _concat_project(self, project: str) -> str:
        return project if self.project_base == "" else f"{self.project_base}:{project}"

    def build_project(self) -> str:
        return self._concat_project(self.build_project_suffix)

    def diff_project(self) -> str:
        return self._concat_project(self.diff_project_suffix)

    @staticmethod
    def from_config_entry(entry: Dict[str, str]) -> Any:
        return IncrementConfig(
            distri=entry["distri"],
            version=entry.get("version", "any"),
            flavor=entry.get("flavor", "any"),
            project_base=entry["project_base"],
            build_project_suffix=entry["build_project_suffix"],
            diff_project_suffix=entry["diff_project_suffix"],
            build_listing_sub_path=entry["build_listing_sub_path"],
            build_regex=entry["build_regex"],
            product_regex=entry["product_regex"],
        )

    @staticmethod
    def from_config_file(file_path: Path) -> List[Any]:
        return map(
            IncrementConfig.from_config_entry,
            YAML(typ="safe").load(file_path)["increment_definitions"],
        )

    @staticmethod
    def from_args(args: Namespace) -> List[Any]:
        if args.increment_config:
            return IncrementConfig.from_config_file(args.increment_config)
        field_mapping = map(lambda field: getattr(args, field), IncrementConfig._fields)
        return [IncrementConfig(*field_mapping)]


class IncrementApprover:
    def __init__(self, args: Namespace) -> None:
        self.args = args
        self.token = {"Authorization": "Token {}".format(args.token)}
        self.client = openQAInterface(args)
        self.repo_diff = None
        self.config = IncrementConfig.from_args(args)
        osc.conf.get_config(override_apiurl=OBS_URL)

    def _find_request_on_obs(
        self, config: IncrementConfig
    ) -> Optional[osc.core.Request]:
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
            obs_requests = osc.core.get_request_list(
                OBS_URL, project=build_project, req_state=relevant_states
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
        self, build_info: BuildInfo, params: List[Dict[str, str]]
    ) -> List[Dict[str, Dict[str, Dict[str, Any]]]]:
        log.debug("Checking openQA job results for %s", build_info)
        query_params = map(
            lambda p: {
                "distri": p["DISTRI"],
                "version": p["VERSION"],
                "flavor": p["FLAVOR"],
                "arch": p["ARCH"],
                "build": p["BUILD"],
            },
            params,
        )
        res = [self.client.get_scheduled_product_stats(p) for p in query_params]
        log.debug("Job statistics:\n%s", pformat(res))
        return res

    def _check_openqa_jobs(
        self, results: List[Dict[str, Dict[str, Dict[str, Any]]]], build_info: BuildInfo
    ) -> Optional[bool]:
        actual_states = set(next(res.keys() for res in results))
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
            job_list = "\n".join(map(lambda id: f" - {openqa_url}/tests/{id}", job_ids))
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

    def _determine_build_info(self, config: IncrementConfig) -> Set[BuildInfo]:
        # deduce DISTRI, VERSION, FLAVOR, ARCH and BUILD from the spdx files in the repo listing similar to the sync plugin
        base_path = config.build_project().replace(":", ":/")
        sub_path = config.build_listing_sub_path
        url = f"{OBS_DOWNLOAD_URL}/{base_path}/{sub_path}/?jsontable=1"
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

    def _make_scheduling_parameters(
        self, config: IncrementConfig, build_info: BuildInfo
    ) -> List[Dict[str, str]]:
        base_params = {
            "DISTRI": build_info.distri,
            "VERSION": build_info.version,
            "FLAVOR": build_info.flavor,
            "ARCH": build_info.arch,
            "BUILD": build_info.build,
        }
        extra_params = [{}]
        if config.diff_project_suffix != "none":
            diff_project = config.diff_project()
            if self.repo_diff is None:
                log.debug("Comuting diff to project %s", diff_project)
                self.repo_diff = RepoDiff(self.args).compute_diff(
                    diff_project, config.build_project() + "/product"
                )[0]
            relevant_diff = self.repo_diff[build_info.arch] | self.repo_diff["noarch"]
            extra_params.extend(
                self._extra_builds_for_kernel_livepatching(relevant_diff, build_info)
            )
        return [*map(lambda p: merge_dicts(base_params, p), extra_params)]

    def _schedule_openqa_jobs(
        self, build_info: BuildInfo, params: List[Dict[str, str]]
    ) -> int:
        log.info("Scheduling jobs for %s", build_info)
        error_count = 0
        for p in params:
            if self.args.dry:
                log.info(p)
                continue
            try:
                self.client.post_job(p)
            except PostOpenQAError:
                error_count += 1
        return error_count

    def _process_request_for_config(
        self, request: Optional[osc.core.Request], config: IncrementConfig
    ) -> int:
        error_count = 0
        if request is None:
            return error_count
        for build_info in self._determine_build_info(config):
            params = self._make_scheduling_parameters(config, build_info)
            res = self._request_openqa_job_results(build_info, params)
            if self.args.reschedule:
                error_count += self._schedule_openqa_jobs(build_info, params)
                continue
            openqa_jobs_ready = self._check_openqa_jobs(res, build_info)
            if openqa_jobs_ready is None and self.args.schedule:
                error_count += self._schedule_openqa_jobs(build_info, params)
                continue
            if not openqa_jobs_ready:
                continue
            error_count += self._handle_approval(
                request, *(self._evaluate_list_of_openqa_job_results(res))
            )
        return error_count

    def __call__(self) -> int:
        error_count = 0
        for config in self.config:
            request = self._find_request_on_obs(config)
            error_count += self._process_request_for_config(request, config)
            self.repo_diff = None
        return error_count
