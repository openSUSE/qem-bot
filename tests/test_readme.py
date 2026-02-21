# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test Readme."""

import os
import subprocess  # noqa: S404
import sys
from pathlib import Path

import pytest


def test_readme_usage_up_to_date() -> None:
    """Ensure the Usage section in Readme.md matches current --help output."""
    env = os.environ.copy()
    env["COLUMNS"] = "80"
    env["NO_COLOR"] = "1"
    result = subprocess.run(  # noqa: S603
        [sys.executable, "qem-bot.py", "--help"],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    help_output = result.stdout
    lines = help_output.splitlines()
    indented_lines = [("    " + line).rstrip() for line in lines]
    formatted_help = "\n".join(indented_lines)
    expected_block = f"    >>> qem-bot.py --help\n{formatted_help}"
    readme_path = Path("Readme.md")
    content = readme_path.read_text(encoding="utf-8")
    content = content.replace("\r\n", "\n")
    expected_block = expected_block.replace("\r\n", "\n")
    assert expected_block in content, (
        "Readme.md usage section is outdated. "
        "Run 'python3 scripts/update_readme.py' or 'make update-readme' to update it."
    )


def run_readme_line_length_check(readme_content: str) -> None:
    max_length = 80
    lines = readme_content.splitlines()

    in_usage_section = False
    for i, line in enumerate(lines, start=1):
        if "<!-- usage_start -->" in line:
            in_usage_section = True
            continue
        if "<!-- usage_end -->" in line:
            in_usage_section = False
            continue
        if in_usage_section:
            continue
        if len(line) <= max_length:
            continue
        if "http://" in line or "https://" in line:
            continue
        pytest.fail(f"Line {i} in Readme.md exceeds {max_length} characters:\n{line}")


def test_readme_line_length_success() -> None:
    """Ensure Readme.md lines do not exceed a limit, excluding long URLs and generated usage."""
    readme_content = (
        "# Title\n"
        "This is a short line.\n"
        "<!-- usage_start -->\n"
        "This line is very long but it is in the usage section so it should be ignored by the test.\n"
        "<!-- usage_end -->\n"
        "https://this.is.a.very.long.url.that.exceeds.the.maximum.line.length.but.should.be.ignored.by.the.test.com\n"
    )
    run_readme_line_length_check(readme_content)


def test_readme_line_length_failure() -> None:
    """Ensure Readme.md lines exceeding the limit without being a URL or in usage fail."""
    readme_content = (
        "This is a very long line that is not a URL and not in the usage section, so it should fail the test.\n"
    )
    with pytest.raises(pytest.fail.Exception, match="exceeds 80 characters"):
        run_readme_line_length_check(readme_content)


def test_readme_actual_file() -> None:
    """Verify the actual Readme.md file in the repository."""
    readme_path = Path("Readme.md")
    readme_content = readme_path.read_text(encoding="utf-8")
    run_readme_line_length_check(readme_content)
