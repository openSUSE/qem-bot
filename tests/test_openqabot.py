#!/usr/bin/python3
# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

import pytest
import sys

from openqabot.main import main  # SUT


def test_help():
    sys.argv += "--help".split()
    with pytest.raises(SystemExit):
        main()
