# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Gitea Pullrequest type definition."""

from dataclasses import dataclass, field
from typing import Any, Protocol


class CommentableProtocol(Protocol):
    """Protocol for objects representing a commentable entity."""

    @property
    def id(self) -> int:
        """The identifier of the pull request."""
        ...

    @property
    def url(self) -> str | None:
        """The URL of the pull request."""
        ...


@dataclass
class PullRequest:
    """Represent all information to operate Gitea pull requests."""

    number: int
    repo_name: str
    branch: str
    url: str
    commit_sha: str
    raw_labels: list[dict[str, Any]] = field(repr=False)

    labels: set[str] = field(init=False)

    @property
    def id(self) -> int:
        """Alias for number for consistency with Submission."""
        return self.number

    def __post_init__(self) -> None:
        """Extract names from the raw label dictionaries into a set."""
        self.labels = {label["name"] for label in self.raw_labels}

    def has_all_labels(self, required_labels: set[str]) -> bool:
        """Check if pull request has ALL labels provided in the input list."""
        return self.labels.issuperset(required_labels)

    def has_any_label(self, search_labels: set[str]) -> bool:
        """Check if pull request has at least one label from the input set."""
        return not self.labels.isdisjoint(search_labels)
