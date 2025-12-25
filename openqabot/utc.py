# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
try:
    from datetime import UTC  # type: ignore[unresolved-import]
except ImportError:  # pragma: no cover
    from datetime import timezone

    UTC = timezone.utc
