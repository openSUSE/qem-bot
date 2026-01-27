#!/usr/bin/env python3
# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import logging
import os
import re
import subprocess  # noqa: S404
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def get_help_output() -> str:
    env = os.environ.copy()
    env["COLUMNS"] = "80"
    result = subprocess.run(  # noqa: S603
        [sys.executable, "qem-bot.py", "--help"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout


def format_block(help_text: str) -> str:
    lines = help_text.splitlines()
    indented_lines = [("    " + line).rstrip() for line in lines]
    return "\n".join(indented_lines)


def update_readme() -> None:
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
    assert match
    current_content = match.group(2)
    if current_content == new_section_content:
        log.info("Readme.md is already up to date.")
        return
    new_content = pattern.sub(lambda m: m.group(1) + new_section_content + m.group(3), content)
    readme_path.write_text(new_content, encoding="utf-8")
    log.info("Updated Readme.md with latest help output.")


if __name__ == "__main__":
    update_readme()
