# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""UTC timezone import compatibility."""

try:
    from datetime import UTC  # type: ignore[unresolved-import]
except ImportError:  # pragma: no cover
    from datetime import timezone

    UTC = timezone.utc
