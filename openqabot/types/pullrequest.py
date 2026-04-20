# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Gitea Pullrequest type definition."""

from dataclasses import dataclass, field
from logging import getLogger
from typing import Any, Protocol, Self

log = getLogger("bot.loader.pullrequest")


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
    state: str
    project: str
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

    def is_active(self) -> bool:
        """Check if the pull request is in an active state."""
        return self.state == "open"

    @classmethod
    def from_json(cls: type[Self], pr_json: dict[str, Any]) -> Self | None:
        """Return instance of PullRequest created from dict."""
        try:
            instance = cls(
                number=pr_json["number"],
                state=pr_json.get("state", "open"),
                raw_labels=pr_json.get("labels", []),
                project=pr_json["base"]["repo"]["full_name"],
                branch=pr_json["base"].get("label", pr_json["base"].get("ref", "unknown")),
                url=pr_json.get("html_url", pr_json.get("url", "")),
                commit_sha=pr_json.get("head", {}).get("sha", "unknown"),
            )
            log.debug("PR git:%i: %s", instance.number, instance)
        except KeyError:
            pr_id = pr_json.get("number", "?")
            log.exception("PR git:%s ignored: Could not read PR metadata", pr_id)
            return None
        else:
            return instance
