# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Trigger configuration loader."""

from __future__ import annotations

import pprint
from dataclasses import dataclass, field, fields
from logging import getLogger
from typing import Any

from .gitea import VERSION_EXTRACT_REGEX

log = getLogger("bot.loader.triggerconfig")


@dataclass
class TriggerConfig:
    """Base configuration for product increments."""

    distri: str
    flavor: str = "any"
    branch: str = "slfo-main"
    project: str = "SLFO"
    repo_template: str = "None"
    image_regex: str = ""
    settings: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        """Return a string representation of the increment configuration."""
        settings_str = pprint.pformat(self.settings, compact=True, depth=1) if self.settings else "no settings"
        return f"{self.distri} ({settings_str})"

    def generate_obs_repo_url(self, pr_id: int, repo_prefix: str, *, is_opensuse: bool) -> str:
        """Generate OBS repository URL based on openSUSE or other distris."""
        if is_opensuse:
            return self.repo_template.format(
                repo_prefix=repo_prefix,
                version=self.get_branch_version(),
                pr_id=pr_id,
            )
        return self.repo_template.format(
            repo_prefix=repo_prefix,
            project=self.project,
            pr_id=pr_id,
        )

    def get_build_project(self) -> str:
        """Get the OBS build project name with slashes replaced."""
        return self.project.replace("/", "_")

    def get_branch_version(self) -> str:
        """Extract the branch version using a regex."""
        matches = VERSION_EXTRACT_REGEX.search(self.branch)
        if not matches:
            error_msg = f"Could not get version from {self.branch}"
            log.error(error_msg)
            raise ValueError(error_msg)
        return matches.group(0)

    def get_os_template_setting(self) -> str:
        """Retrieve and format OS_TEST_TEMPLATE setting with the branch version."""
        if "OS_TEST_TEMPLATE" in self.settings:
            return self.settings["OS_TEST_TEMPLATE"].format(version=self.get_branch_version())
        error_msg = f"{self!s} does not have expected OS_TEST_TEMPLATE"
        raise ValueError(error_msg)

    @classmethod
    def from_config_entry(cls, entry: dict[str, Any]) -> TriggerConfig:
        """Create an BaseConfig from a dictionary entry."""
        known = {f.name for f in fields(cls)}
        return cls(distri=entry["distri"], **{k: v for k, v in entry.items() if k != "distri" and k in known})
