#!/usr/bin/env python3
# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Script to update Readme.md."""

import logging
import os
import re
import subprocess  # noqa: S404
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from text."""
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)


def get_help_output() -> str:
    """Run qem-bot.py --help and return the output."""
    env = os.environ.copy()
    env["COLUMNS"] = "80"
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    process = subprocess.run(  # noqa: S603
        [sys.executable, "qem-bot.py", "--help"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return strip_ansi(process.stdout)


def format_block(help_text: str) -> str:
    """Format help text as an indented block."""
    lines = help_text.splitlines()
    indented_lines = [("    " + line.strip()).rstrip() for line in lines]
    return "\n".join(indented_lines)


def update_readme() -> None:
    """Update the 'General Usage' section in Readme.md with current help output."""
    readme_path = Path("Readme.md")
    content = readme_path.read_text(encoding="utf-8")
    help_output = get_help_output()
    formatted_help = format_block(help_output)
    start_marker = "<!-- usage_start -->"
    end_marker = "<!-- usage_end -->"
    pattern = re.compile(f"({re.escape(start_marker)})(.*?)({re.escape(end_marker)})", re.DOTALL)
    new_section_content = f"\n\n    >>> qem-bot.py --help\n{formatted_help}\n\n"
    match = pattern.search(content)
    if not match:
        log.error("Could not find Usage section in Readme.md")
        sys.exit(1)
    assert match  # noqa: S101
    current_content = match.group(2)
    if current_content == new_section_content:
        log.info("Readme.md is already up to date.")
        return
    new_content = pattern.sub(lambda m: m.group(1) + new_section_content + m.group(3), content)
    readme_path.write_text(new_content, encoding="utf-8")
    log.info("Updated Readme.md with latest help output.")


if __name__ == "__main__":
    update_readme()
