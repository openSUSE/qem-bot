# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Submission identity as addressed by the QEM dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openqabot.errors import SubmissionArgError

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

    def to_dashboard_params(self) -> dict[str, str]:
        """Return the dashboard query parameters that address this incident."""
        return {"project": self.project, "type": self.type}

    @classmethod
    def from_submission_dict(cls, submission: dict[str, Any]) -> SubmissionKey:
        """Return the key of a submission record built by ``_init_submission_dict``."""
        return cls(GITEA_TYPE, submission["project"], submission["number"])

    def __str__(self) -> str:
        """Return the canonical ``<type>:<project>:<id>`` form."""
        return f"{self.type}:{self.project}:{self.number}"
