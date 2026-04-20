# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test configuration."""

import ast
from pathlib import Path
from unittest.mock import patch

import pytest

from openqabot.config import Settings, get_default_obs_url


def _keyword_str_values(tree: ast.AST, arg: str) -> set[str]:
    return {
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword)
        and node.arg == arg
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def test_download_maintenance_override() -> None:
    """Test that download_maintenance_base_url overrides the default."""
    settings = Settings(download_maintenance_base_url="http://custom.url")
    assert settings.download_maintenance == "http://custom.url"


def test_git_review_bot_user_default() -> None:
    """Test the default value for git_review_bot_user."""
    settings = Settings(obs_group="mygroup")
    assert settings.git_review_bot_user == "mygroup-review"


def test_git_review_bot_user_override() -> None:
    """Test that GIT_REVIEW_BOT overrides the default."""
    settings = Settings(git_review_bot="mybot")
    assert settings.git_review_bot_user == "mybot"


def test_git_review_bot_user_empty() -> None:
    """Test that explicit empty GIT_REVIEW_BOT disables the bot user."""
    settings = Settings(git_review_bot="")
    assert not settings.git_review_bot_user


def test_get_default_obs_url_from_osc() -> None:
    """Test that get_default_obs_url derives the URL from osc.conf."""
    with patch("osc.conf.get_config"), patch("osc.conf.config", {"apiurl": "https://api.example.com"}):
        assert get_default_obs_url() == "https://api.example.com"


def test_get_default_obs_url_no_apiurl() -> None:
    """Test that get_default_obs_url falls back to default if apiurl is missing in osc.conf."""
    with patch("osc.conf.get_config"), patch("osc.conf.config", {}):
        assert get_default_obs_url() == "https://api.suse.de"


def test_get_default_obs_url_fallback() -> None:
    """Test that get_default_obs_url falls back to default if osc.conf fails."""
    with patch("osc.conf.get_config", side_effect=Exception("osc not configured")):
        assert get_default_obs_url() == "https://api.suse.de"


def test_cli_envvars_covered_by_settings() -> None:
    """Every envvar= in args.py must have a matching alias= in config.py Settings."""
    cli_envvars = _keyword_str_values(ast.parse(Path("openqabot/args.py").read_text(encoding="utf-8")), "envvar")
    config_aliases = _keyword_str_values(ast.parse(Path("openqabot/config.py").read_text(encoding="utf-8")), "alias")
    missing = cli_envvars - config_aliases
    assert not missing, f"envvars in args.py missing from config.py Settings: {missing}"


def test_obs_web_url_property(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the obs_web_url property."""
    monkeypatch.delenv("OBS_URL", raising=False)
    settings = Settings(obs_url="https://api.suse.de")
    assert settings.obs_web_url == "https://build.suse.de"

    settings = Settings(obs_url="https://api.opensuse.org")
    assert settings.obs_web_url == "https://build.opensuse.org"

    settings = Settings(obs_url="https://some.api.server.com")
    assert settings.obs_web_url == "https://some.build.server.com"


def test_obs_products_set() -> None:
    """Test the obs_products_set property."""
    settings = Settings(obs_products="p1,p2,p3")
    assert settings.obs_products_set == {"p1", "p2", "p3"}


def test_dashboard_token_dict() -> None:
    """Test the dashboard_token_dict property."""
    settings = Settings(token="mytoken")
    assert settings.dashboard_token_dict == {"Authorization": "Token mytoken"}


def test_insecure_setting() -> None:
    """Test the insecure setting."""
    settings = Settings(insecure=True)
    assert settings.insecure is True

    settings = Settings(insecure=False)
    assert settings.insecure is False
