# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Configuration constants.

This module defines configuration constants used throughout the application.
Most of these constants can be overridden by environment variables.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import osc.conf
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_default_obs_url() -> str:
    """Get the default OBS URL from osc configuration."""
    try:
        osc.conf.get_config()
        if apiurl := osc.conf.config.get("apiurl"):
            return apiurl
    except Exception:  # noqa: BLE001, S110
        pass
    return "https://api.suse.de"


class Settings(BaseSettings):
    """Configuration settings managed by Pydantic."""

    # Global options
    configs: Path = Field(default=Path("/etc/openqabot"), alias="QEM_BOT_CONFIGS")
    dry: bool = Field(default=False, alias="QEM_BOT_DRY")
    fake_data: bool = Field(default=False, alias="QEM_BOT_FAKE_DATA")
    dump_data: bool = Field(default=False, alias="QEM_BOT_DUMP_DATA")
    debug: bool = Field(default=False, alias="QEM_BOT_DEBUG")
    token: str | None = Field(default=None, alias="QEM_BOT_TOKEN")
    gitea_token: str | None = Field(default=None, alias="QEM_BOT_GITEA_TOKEN")
    openqa_instance: str = Field(default="https://openqa.suse.de", alias="OPENQA_INSTANCE")
    singlearch: Path = Field(default=Path("/etc/openqabot/singlearch.yml"), alias="QEM_BOT_SINGLEARCH")
    retry: int = Field(default=2, alias="QEM_BOT_RETRY")

    # App-specific settings
    qem_dashboard_url: str = Field(default="http://dashboard.qam.suse.de/", alias="QEM_DASHBOARD_URL")
    smelt_url: str = Field(default="https://smelt.suse.de", alias="SMELT_URL")
    gitea_url: str = Field(default="https://src.suse.de", alias="GITEA_URL")
    obs_url: str = Field(default_factory=get_default_obs_url, alias="OBS_URL")
    obs_download_url: str = Field(default="http://download.suse.de/ibs", alias="OBS_DOWNLOAD_URL")
    obs_repo_type: str | None = Field(default="product", alias="OBS_REPO_TYPE")
    obs_products: str = Field(default="all", alias="OBS_PRODUCTS")
    allow_development_groups: str | None = Field(default=None, alias="QEM_BOT_ALLOW_DEVELOPMENT_GROUPS")
    development_parent_group_id: int = 9
    download_base_url: str = Field(default="http://%REPO_MIRROR_HOST%/ibs", alias="DOWNLOAD_BASE_URL")
    download_maintenance_base_url: str | None = Field(default=None, alias="DOWNLOAD_MAINTENANCE_BASE_URL")
    amqp_url: str = Field(default="amqps://suse:suse@rabbit.suse.de", alias="AMQP_URL")
    deprioritize_limit: int | None = Field(default=None, alias="QEM_BOT_DEPRIORITIZE_LIMIT")
    base_prio: int = 50
    priority_scale: int = Field(default=20, alias="QEM_BOT_PRIORITY_SCALE")
    main_openqa_domain: str = Field(default="openqa.suse.de", alias="MAIN_OPENQA_DOMAIN")
    git_review_bot: str | None = Field(default=None, alias="GIT_REVIEW_BOT")
    git_obs_staging_bot_user: str = Field(default="autogits_obs_staging_bot", alias="GIT_OBS_STAGING_BOT_USER")
    default_submission_type: str = "smelt"
    obs_maint_prj: str = Field(default="SUSE:Maintenance", alias="OBS_MAINT_PRJ")
    obs_group: str = Field(default="qam-openqa", alias="OBS_GROUP")
    oldest_approval_job_days: int = 6

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        validate_assignment=True,
    )

    @property
    def smelt_graphql(self) -> str:
        """Return the SMELT GraphQL API URL."""
        return self.smelt_url + "/graphql"

    @property
    def obs_web_url(self) -> str:
        """Return the OBS web UI URL."""
        return self.obs_url.replace("api.", "build.")

    @property
    def download_maintenance(self) -> str:
        """Return the maintenance download URL."""
        if self.download_maintenance_base_url:
            return self.download_maintenance_base_url
        return self.download_base_url + "/SUSE:/Maintenance:/"

    @property
    def git_review_bot_user(self) -> str | None:
        """Return the git review bot username."""
        if self.git_review_bot is not None:
            return self.git_review_bot
        return self.obs_group + "-review"

    @property
    def obs_products_set(self) -> set[str]:
        """Return the set of OBS products to consider."""
        return set(self.obs_products.split(","))


settings = Settings()


def __getattr__(name: str) -> Any:  # noqa: ANN401
    """Map legacy module-level constants to settings object attributes."""
    mapping = {
        "QEM_DASHBOARD": "qem_dashboard_url",
        "DEFAULT_SUBMISSION_TYPE": "default_submission_type",
        "SMELT_URL": "smelt_url",
        "SMELT": "smelt_graphql",
        "GITEA": "gitea_url",
        "OBS_URL": "obs_url",
        "OBS_WEB_URL": "obs_web_url",
        "OBS_DOWNLOAD_URL": "obs_download_url",
        "OBS_MAINT_PRJ": "obs_maint_prj",
        "OBS_GROUP": "obs_group",
        "OBS_REPO_TYPE": "obs_repo_type",
        "OBS_PRODUCTS": "obs_products_set",
        "ALLOW_DEVELOPMENT_GROUPS": "allow_development_groups",
        "DEVELOPMENT_PARENT_GROUP_ID": "development_parent_group_id",
        "DOWNLOAD_BASE": "download_base_url",
        "DOWNLOAD_MAINTENANCE": "download_maintenance",
        "AMQP_URL": "amqp_url",
        "OLDEST_APPROVAL_JOB_DAYS": "oldest_approval_job_days",
        "DEPRIORITIZE_LIMIT": "deprioritize_limit",
        "BASE_PRIO": "base_prio",
        "PRIORITY_SCALE": "priority_scale",
        "OPENQA_URL": "main_openqa_domain",
        "GIT_REVIEW_BOT": "git_review_bot_user",
        "GIT_OBS_STAGING_BOT": "git_obs_staging_bot_user",
    }
    if name in mapping:
        return getattr(settings, mapping[name])
    if name == "BUILD_REGEX":
        return (
            r"(?P<product>.*)-(?P<version>[^\-]*?)-(?P<flavor>\D+[^\-]*?)-"
            r"(?P<arch>[^\-]*?)-Build(?P<build>.*?)\.spdx.json"
        )
    if name == "OBSOLETE_PARAMS":
        return {
            "_OBSOLETE": "1",
            "_ONLY_OBSOLETE_SAME_BUILD": "1",
        }
    msg = f"module {__name__} has no attribute {name}"
    raise AttributeError(msg)
