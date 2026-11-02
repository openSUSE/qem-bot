# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Submission identity as addressed by the QEM dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from openqabot.errors import SubmissionArgError

if TYPE_CHECKING:
    from collections.abc import Mapping

GITEA_TYPE = "git"


@dataclass(frozen=True, slots=True)
class SubmissionKey:
    """Dashboard incident key ``(type, project, number)``.

    The canonical string form is ``<type>:<project>:<id>``. Projects may contain
    colons (OBS/SMELT projects do), types and ids never do, so the type ends at
    the first colon and the id starts after the last one.
    """

    type: str
    project: str
    number: int

    @classmethod
    def gitea(cls, project: str, number: int) -> SubmissionKey:
        """Return the key of a Gitea PR."""
        return cls(GITEA_TYPE, project, number)

    @classmethod
    def parse(cls, raw: str) -> SubmissionKey:
        """Parse a ``<type>:<project>:<id>`` string.

        Raises ``SubmissionArgError`` when a part is missing, the id is not
        numeric or the id is zero.
        """
        s_type, sep, rest = raw.partition(":")
        s_project, sep_id, s_id = rest.rpartition(":")
        if not (sep and sep_id and s_type and s_project and s_id):
            raise SubmissionArgError(raw)
        if not (s_id.isascii() and s_id.isdigit()):
            raise SubmissionArgError(raw, numeric=True)
        number = int(s_id)
        if number == 0:
            raise SubmissionArgError(raw, positive=True)
        return cls(s_type, s_project, number)

    def to_dashboard_params(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        """Return the dashboard query parameters that address this incident.

        Optional ``extra`` key/value pairs are merged into the result, so callers
        that need additional query parameters do not have to build the whole
        mapping themselves. An ``extra`` key wins over the identity fields.
        """
        params = {"project": self.project, "type": self.type}
        if extra:
            params.update(extra)
        return params

    @classmethod
    def from_dashboard(cls, incident: dict[str, Any]) -> SubmissionKey:
        """Return the key of a dashboard incident record.

        The record must carry the full identity: a ``KeyError`` is raised when
        ``type``, ``project`` or ``number`` is missing, so callers that tolerate
        a partial record have to check the fields first.
        """
        return cls(incident["type"], incident["project"], incident["number"])

    @classmethod
    def from_submission_dict(cls, submission: dict[str, Any]) -> SubmissionKey:
        """Return the key of a submission record built by ``_init_submission_dict``.

        Such records are always Gitea PRs and do not carry a ``type`` yet.
        """
        return cls(GITEA_TYPE, submission["project"], submission["number"])

    def __str__(self) -> str:
        """Return the canonical ``<type>:<project>:<id>`` form."""
        return f"{self.type}:{self.project}:{self.number}"
