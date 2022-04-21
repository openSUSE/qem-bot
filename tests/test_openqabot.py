#!/usr/bin/python3
# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from openqabot.main import main  # SUT


def test_help():
    sys.argv += "--help".split()
    with pytest.raises(SystemExit):
        main()
