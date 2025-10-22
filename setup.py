# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

from pathlib import Path

from setuptools import setup

setup(
    name="qem-bot",
    version="42",
    license="MIT",
    description="tool for schedule maintenance jobs + sync SMELT/OpenQA to QEM-Dashboard",
    long_description=Path("Readme.md").read_text(),
    long_description_content_type="text/markdown",
    packages=["openqabot", "openqabot.loader", "openqabot.osclib", "openqabot.types"],
    scripts=["qem-bot.py", "pc_helper_online.py"],
)
