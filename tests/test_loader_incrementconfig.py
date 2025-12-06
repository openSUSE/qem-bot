# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from pathlib import Path
from unittest.mock import ANY, patch

from openqabot.loader.incrementconfig import IncrementConfig


def test_from_config_file_invalid_yaml(tmp_path: Path) -> None:
    invalid_yaml_file = tmp_path / "invalid.yml"
    invalid_yaml_file.write_text("key: value:")

    with patch("openqabot.loader.incrementconfig.log") as mock_logger:
        configs = list(IncrementConfig.from_config_file(invalid_yaml_file))

        assert configs == []
        mock_logger.info.assert_any_call("Reading config file '%s'", invalid_yaml_file)
        mock_logger.info.assert_any_call("Unable to load config file '%s': %s", invalid_yaml_file, ANY)
