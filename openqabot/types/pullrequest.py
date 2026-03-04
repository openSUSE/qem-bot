# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Gitea Pullrequest type definition."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PullRequest:
    """Represent all information to operate Gitea pull requests."""

    number: int
    repo_name: str
    branch: str
    product: str
    raw_labels: list[dict[str, Any]] = field(repr=False)

    labels: list[str] = field(init=False)

    def __post_init__(self) -> None:
        """Extract names from the raw label dictionaries."""
        self.labels = [label["name"] for label in self.raw_labels]

    def has_label(self, label: str) -> bool:
        """Check if pull request is labeled with certain label."""
        return label in self.labels
