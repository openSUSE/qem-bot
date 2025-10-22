#!/usr/bin/python3
# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

import sys

import pytest

from openqabot.main import main  # SUT


def test_help():
    sys.argv += ["--help"]
    with pytest.raises(SystemExit):
        main()
