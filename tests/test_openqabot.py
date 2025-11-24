# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

import sys
from unittest.mock import patch

import pytest

from openqabot.main import main  # SUT


def test_help() -> None:
    with patch.object(sys, "argv", ["--help"]), pytest.raises(SystemExit):
        main()


def test_no_args_prints_help() -> None:
    with (
        patch.object(sys, "argv", []),
        patch("openqabot.args.ArgumentParser.print_help"),
        pytest.raises(SystemExit),
    ):
        main()
