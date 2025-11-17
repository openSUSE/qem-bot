# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import pprint
from argparse import Namespace
from dataclasses import dataclass, field
from itertools import chain
from logging import getLogger
from pathlib import Path
from typing import Dict, Iterator, List, Set

from ruamel.yaml import YAML

from .. import OBS_DOWNLOAD_URL
from ..utils import get_yml_list

log = getLogger("bot.increment_config")


@dataclass
class IncrementConfig:
    distri: str
    version: str
    flavor: str
    project_base: str = ""
    build_project_suffix: str = ""
    diff_project_suffix: str = ""
    build_listing_sub_path: str = ""
    build_regex: str = ""
    product_regex: str = ""
    packages: List[str] = field(default_factory=list)
    archs: Set[str] = field(default_factory=set)
    settings: Dict[str, str] = field(default_factory=dict)
    additional_builds: List[Dict[str, str]] = field(default_factory=list)

    def _concat_project(self, project: str) -> str:
        return project if self.project_base == "" else f"{self.project_base}:{project}"

    def build_project(self) -> str:
        return self._concat_project(self.build_project_suffix)

    def diff_project(self) -> str:
        return self._concat_project(self.diff_project_suffix)

    def build_project_url(self, base_url: str = OBS_DOWNLOAD_URL) -> str:
        base_path = self.build_project().replace(":", ":/")
        return f"{base_url}/{base_path}"

    def __str__(self) -> str:
        settings_str = pprint.pformat(self.settings, compact=True, depth=1) if self.settings else "no settings"
        return f"{self.distri} ({settings_str})"

    @staticmethod
    def from_config_entry(entry: Dict[str, str]) -> "IncrementConfig":
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
            packages=entry.get("packages", []),
            archs=set(entry.get("archs", [])),
            settings=entry.get("settings", {}),
            additional_builds=entry.get("additional_builds", []),
        )

    @staticmethod
    def from_config_file(file_path: Path) -> Iterator["IncrementConfig"]:
        try:
            log.info("Reading config file '%s'", file_path)
            return map(
                IncrementConfig.from_config_entry,
                YAML(typ="safe").load(file_path).get("product_increments", []),
            )
        except Exception as e:  # noqa: BLE001 true-positive: Consider to use fine-grained exceptions
            log.info("Unable to load config file '%s': %s", file_path, e)
            return iter(())

    @staticmethod
    def from_config_path(file_or_dir_path: Path) -> Iterator["IncrementConfig"]:
        return chain.from_iterable(IncrementConfig.from_config_file(p) for p in get_yml_list(file_or_dir_path))

    @staticmethod
    def from_args(args: Namespace) -> List["IncrementConfig"]:
        if args.increment_config:
            return IncrementConfig.from_config_path(args.increment_config)
        # Create a dictionary from arguments for IncrementConfig
        config_args = {
            field_name: getattr(args, field_name)
            for field_name in [
                "distri",
                "version",
                "flavor",
                "project_base",
                "build_project_suffix",
                "diff_project_suffix",
                "build_listing_sub_path",
                "build_regex",
                "product_regex",
                "packages",
                "archs",
                "settings",
                "additional_builds",
            ]
            if hasattr(args, field_name)
        }
        return [IncrementConfig(**config_args)]
