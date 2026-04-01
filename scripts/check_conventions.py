#!/usr/bin/env python3
# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Script to check project coding conventions."""

import logging
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

# Patterns to check
STATICMETHOD_PATTERN = re.compile(r"^\s*@staticmethod")
FACTORY_PATTERN = re.compile(r"^\s*def from_")
DECORATOR_OR_COMMENT_PATTERN = re.compile(r"^\s*[@#]")


def check_staticmethods(path: Path) -> int:
    """Ensure @staticmethod is only used for factory methods (starts with from_)."""
    errors = 0
    lines = path.read_text(encoding="utf-8").splitlines()

    for i, line in enumerate(lines):
        if not STATICMETHOD_PATTERN.match(line):
            continue

        # Look ahead for the function definition
        found_factory = False
        for next_line in lines[i + 1 :]:
            if not DECORATOR_OR_COMMENT_PATTERN.match(next_line):
                if FACTORY_PATTERN.match(next_line):
                    found_factory = True
                break

        if not found_factory:
            log.error("%s:%i: @staticmethod forbidden. Use free functions instead.", path, i + 1)
            errors += 1

    return errors


def main() -> int:
    """Run convention checks on source files."""
    project_root = Path(__file__).resolve().parent.parent
    source_dir = project_root / "openqabot"
    total_errors = 0

    for path in source_dir.rglob("*.py"):
        total_errors += check_staticmethods(path)

    if total_errors:
        log.error("Total convention errors: %i", total_errors)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
