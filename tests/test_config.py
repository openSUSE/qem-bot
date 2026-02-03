# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Test configuration."""

from openqabot.config import Settings


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
