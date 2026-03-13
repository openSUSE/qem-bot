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

    labels: set[str] = field(init=False)

    def __post_init__(self) -> None:
        """Extract names from the raw label dictionaries into a set."""
        self.labels = {label["name"] for label in self.raw_labels}

    def has_labels(self, required_labels: set[str]) -> bool:
        """Check if pull request has ALL labels provided in the input list."""
        return self.labels.issuperset(required_labels)
