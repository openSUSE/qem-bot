# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Increment configuration loader."""

from __future__ import annotations

import pprint
from dataclasses import dataclass, field
from itertools import chain
from logging import getLogger
from typing import TYPE_CHECKING, Any

import ruamel.yaml
from ruamel.yaml import YAML

from openqabot import config
from openqabot.utils import get_yml_list

if TYPE_CHECKING:
    from argparse import Namespace
    from collections.abc import Iterator
    from pathlib import Path

log = getLogger("bot.increment_config")
DEFAULT_FLAVOR_SUFFIX = "Increments"
DEFAULT_VERSION_REGEX = r"[\d.]+"


@dataclass
class IncrementConfig:
    """Configuration for product increments."""

    distri: str
    version: str
    flavor: str
    flavor_suffix: str = DEFAULT_FLAVOR_SUFFIX
    project_base: str = ""
    build_project_suffix: str = ""
    diff_project_suffix: str = ""
    build_listing_sub_path: str = ""
    build_regex: str = ""
    product_regex: str = ""
    version_regex: str = DEFAULT_VERSION_REGEX
    packages: list[str] = field(default_factory=list)
    archs: set[str] = field(default_factory=set)
    settings: dict[str, str] = field(default_factory=dict)
    additional_builds: list[dict[str, Any]] = field(default_factory=list)
    reference_repos: dict[str, str] = field(default_factory=dict)

    def _concat_project(self, project: str) -> str:
        if not self.project_base:
            return project
        if not project:
            return self.project_base
        return f"{self.project_base}:{project}"

    def build_project(self) -> str:
        """Return the build project name."""
        return self._concat_project(self.build_project_suffix)

    def diff_project(self) -> str:
        """Return the project name to compute diff against."""
        return self._concat_project(self.diff_project_suffix)

    def build_project_url(self, base_url: str | None = None) -> str:
        """Return the URL of the build project."""
        base_path = self.build_project().replace(":", ":/")
        return f"{base_url or config.settings.obs_download_url}/{base_path}"

    def __str__(self) -> str:
        """Return a string representation of the increment configuration."""
        settings_str = pprint.pformat(self.settings, compact=True, depth=1) if self.settings else "no settings"
        return f"{self.distri} ({settings_str})"

    @staticmethod
    def from_config_entry(entry: dict[str, Any]) -> IncrementConfig:
        """Create an IncrementConfig from a dictionary entry."""
        return IncrementConfig(
            distri=entry["distri"],
            version=entry.get("version", "any"),
            flavor=entry.get("flavor", "any"),
            flavor_suffix=entry.get("flavor_suffix", DEFAULT_FLAVOR_SUFFIX),
            project_base=entry["project_base"],
            build_project_suffix=entry["build_project_suffix"],
            diff_project_suffix=entry["diff_project_suffix"],
            build_listing_sub_path=entry["build_listing_sub_path"],
            build_regex=entry["build_regex"],
            product_regex=entry["product_regex"],
            version_regex=entry.get("version_regex", DEFAULT_VERSION_REGEX),
            packages=entry.get("packages", []),
            archs=set(entry.get("archs", [])),
            settings=entry.get("settings", {}),
            additional_builds=entry.get("additional_builds", []),
            reference_repos=entry.get("reference_repos", {}),
        )

    @staticmethod
    def from_config_file(file_path: Path, *, load_defaults: bool = True) -> Iterator[IncrementConfig]:
        """Load increment configurations from a YAML file."""
        try:
            log.debug("Loading increment configuration from '%s'", file_path)
            yaml = YAML(typ="safe").load(file_path)
            items = list(
                map(
                    IncrementConfig.from_config_entry,
                    yaml.get("product_increments", []),
                )
            )
            # Apply default settings to all items
            if load_defaults:
                defaults = yaml.get("settings", {})
                for item in items:
                    item.settings = defaults | item.settings
        except AttributeError:
            log.debug("File '%s' skipped: Not a valid increment configuration", file_path)
            return iter(())
        except (ruamel.yaml.YAMLError, FileNotFoundError, PermissionError) as e:
            log.info("Increment configuration skipped: Could not load '%s': %s", file_path, e)
            return iter(())
        else:
            return iter(items)

    @staticmethod
    def from_config_path(file_or_dir_path: Path) -> Iterator[IncrementConfig]:
        """Load increment configurations from a file or directory."""
        return chain.from_iterable(IncrementConfig.from_config_file(p) for p in get_yml_list(file_or_dir_path))

    @staticmethod
    def from_args(args: Namespace) -> list[IncrementConfig]:
        """Create increment configurations from command line arguments."""
        if args.increment_config:
            return list(IncrementConfig.from_config_path(args.increment_config))
        # Create a dictionary from arguments for IncrementConfig
        config_args = {
            field_name: getattr(args, field_name)
            for field_name in [
                "distri",
                "version",
                "flavor",
                "flavor_suffix",
                "project_base",
                "build_project_suffix",
                "diff_project_suffix",
                "build_listing_sub_path",
                "build_regex",
                "product_regex",
                "version_regex",
                "packages",
                "archs",
                "settings",
                "additional_builds",
                "reference_repos",
            ]
            if hasattr(args, field_name)
        }
        return [IncrementConfig(**config_args)]
