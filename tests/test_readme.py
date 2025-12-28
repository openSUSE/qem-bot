# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import os
import subprocess  # noqa: S404
from pathlib import Path


def test_readme_usage_up_to_date() -> None:
    """Ensure the Usage section in Readme.md matches current --help output."""
    env = os.environ.copy()
    env["COLUMNS"] = "80"
    result = subprocess.run(
        ["python3", "qem-bot.py", "--help"],  # noqa: S607
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
