# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Increment configuration loader."""

from __future__ import annotations

import pprint
import re
from dataclasses import dataclass, field, fields, replace
from logging import getLogger
from typing import TYPE_CHECKING, Any

from openqabot import config

from .config import get_configs_from_path

if TYPE_CHECKING:
    from argparse import Namespace

    from openqabot.types.increment import BuildInfo

log = getLogger("bot.increment_config")
DEFAULT_FLAVOR_SUFFIX = "Increments"
DEFAULT_VERSION_REGEX = r"[\d.]+"


@dataclass(frozen=True)
class GroupKey:
    """Unique key for grouping increment configurations."""

    build_project: str
    build_listing_sub_path: str
    build_regex: str
    distri: str
    flavor_suffix: str


@dataclass
class IncrementConfig:
    """Configuration for product increments."""

    distri: str
    version: str
    flavor: str
    arch: str = "any"
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
    build_repo_template: str = ""
    diff_repo_template: str = ""

    def _concat_project(self, project: str) -> str:
        if not self.project_base:
            return project
        if not project:
            return self.project_base
        return f"{self.project_base}:{project}"

    def build_project(self) -> str:
        """Return the build project name."""
        return self._concat_project(self.build_project_suffix)

    @staticmethod
    def to_url(path: str, base_url: str | None = None) -> str:
        """Return the absolute HTTP URL for a given path or OBS project."""
        if path.startswith(("http://", "https://")):
            return path
        return f"{base_url or config.settings.obs_download_url}/{path.replace(':', ':/')}"

    def build_project_url(self, base_url: str | None = None) -> str:
        """Return the URL of the build project."""
        return self.to_url(self.build_project(), base_url)

    def diff_project_url(self, base_url: str | None = None) -> str:
        """Return the URL of the diff project."""
        return self.to_url(self._concat_project(self.diff_project_suffix), base_url)

    @property
    def group_key(self) -> GroupKey:
        """Return a unique key for grouping configs."""
        return GroupKey(
            build_project=self.build_project(),
            build_listing_sub_path=self.build_listing_sub_path,
            build_regex=self.build_regex,
            distri=self.distri,
            flavor_suffix=self.flavor_suffix,
        )

    def accepts_build_info(self, build_info: BuildInfo) -> bool:
        """Return True if the build information matches this configuration."""
        if not all(
            getattr(self, k) in {"any", getattr(build_info, k)} for k in ("distri", "flavor", "version", "arch")
        ):
            return False
        if self.archs and build_info.arch not in self.archs:
            return False
        if not re.search(self.product_regex, build_info.product):
            return False
        return bool(re.search(self.version_regex, build_info.version))

    def __str__(self) -> str:
        """Return a string representation of the increment configuration."""
        settings_str = pprint.pformat(self.settings, compact=True, depth=1) if self.settings else "no settings"
        return f"{self.distri} ({settings_str})"

    @classmethod
    def from_config_entry(cls, entry: dict[str, Any]) -> IncrementConfig:
        """Create an IncrementConfig from a dictionary entry."""
        return cls(
            distri=entry["distri"],
            version=entry.get("version", "any"),
            flavor=entry.get("flavor", "any"),
            arch=entry.get("arch", "any"),
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
            build_repo_template=entry.get("build_repo_template", ""),
            diff_repo_template=entry.get("diff_repo_template", ""),
        )

    @staticmethod
    def from_args(args: Namespace) -> list[IncrementConfig]:
        """Create increment configurations from command line arguments."""
        source = args.increment_config or (
            args.configs if getattr(args, "configs", None) and args.configs.exists() else None
        )

        if source:
            configs = get_configs_from_path(source, "product_increments", IncrementConfig.from_config_entry)
            if configs:
                return IncrementConfig._apply_cli_overrides(configs, args)

        return [IncrementConfig._create_from_args(args)]

    @staticmethod
    def _apply_cli_overrides(configs: list[IncrementConfig], args: Namespace) -> list[IncrementConfig]:
        """Apply CLI argument overrides to loaded configs.

        Only override when CLI args differ from expected defaults (not dataclass defaults).
        This allows configs to specify their own values while still supporting CLI overrides.
        """
        cli_defaults = {"distri": "sle", "version": "any", "flavor": "any", "arch": "any"}
        overrides = {}

        for field_name, default_value in cli_defaults.items():
            if hasattr(args, field_name) and (arg_value := getattr(args, field_name)) != default_value:
                overrides[field_name] = arg_value

        return [replace(config, **overrides) if overrides else config for config in configs]

    @staticmethod
    def _create_from_args(args: Namespace) -> IncrementConfig:
        """Create a single IncrementConfig from CLI arguments."""
        all_fields = {f.name for f in fields(IncrementConfig)}
        config_args = {field_name: getattr(args, field_name) for field_name in all_fields if hasattr(args, field_name)}
        return IncrementConfig(**config_args)
