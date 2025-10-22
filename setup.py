#!/usr/bin/python3
# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

from setuptools import setup

setup(
    name="qem-bot",
    version="42",
    license="MIT",
    description="tool for schedule maintenance jobs + sync SMELT/OpenQA to QEM-Dashboard",
    long_description=open("Readme.md").read(),
    long_description_content_type="text/markdown",
    packages=["openqabot", "openqabot.loader", "openqabot.osclib", "openqabot.types"],
    scripts=["qem-bot.py", "pc_helper_online.py"],
)
