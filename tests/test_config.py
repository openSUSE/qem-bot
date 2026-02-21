# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test configuration."""

from unittest.mock import patch

from openqabot.config import Settings, get_default_obs_url


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


def test_obs_web_url_property() -> None:
    """Test the obs_web_url property."""
    settings = Settings(obs_url="https://api.suse.de")
    assert settings.obs_web_url == "https://build.suse.de"

    settings = Settings(obs_url="https://api.opensuse.org")
    assert settings.obs_web_url == "https://build.opensuse.org"

    settings = Settings(obs_url="https://some.api.server.com")
    assert settings.obs_web_url == "https://some.build.server.com"
