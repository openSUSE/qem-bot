# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Configuration constants.

This module defines configuration constants used throughout the application.
Most of these constants can be overridden by environment variables.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings managed by Pydantic."""

    qem_dashboard_url: str = Field(default="http://dashboard.qam.suse.de/", alias="QEM_DASHBOARD_URL")
    smelt_url: str = Field(default="https://smelt.suse.de", alias="SMELT_URL")
    gitea_url: str = Field(default="https://src.suse.de", alias="GITEA_URL")
    obs_url: str = Field(default="https://api.suse.de", alias="OBS_URL")
    obs_download_url: str = Field(default="http://download.suse.de/ibs", alias="OBS_DOWNLOAD_URL")
    obs_repo_type: str = Field(default="product", alias="OBS_REPO_TYPE")
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
    default_submission_type: str = "smelt"
    obs_maint_prj: str = Field(default="SUSE:Maintenance", alias="OBS_MAINT_PRJ")
    obs_group: str = Field(default="qam-openqa", alias="OBS_GROUP")
    oldest_approval_job_days: int = 6

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", populate_by_name=True)

    @property
    def smelt_graphql(self) -> str:
        """Return the SMELT GraphQL API URL."""
        return self.smelt_url + "/graphql"

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

# Used configuration parameters, e.g. api url's
# Dashboard URL.
QEM_DASHBOARD = settings.qem_dashboard_url
DEFAULT_SUBMISSION_TYPE = settings.default_submission_type

# SMELT URL.
SMELT_URL = settings.smelt_url
SMELT = settings.smelt_graphql

# Gitea URL.
GITEA = settings.gitea_url

# OBS API URL.
OBS_URL = settings.obs_url

# OBS Download URL (IBS).
OBS_DOWNLOAD_URL = settings.obs_download_url

OBS_MAINT_PRJ = settings.obs_maint_prj
OBS_GROUP = settings.obs_group

# Type of the repository for OBS/IBS.
OBS_REPO_TYPE = settings.obs_repo_type

# OBS products to consider.
OBS_PRODUCTS: set[str] = settings.obs_products_set

# Allow scheduling in development groups.
ALLOW_DEVELOPMENT_GROUPS = settings.allow_development_groups
DEVELOPMENT_PARENT_GROUP_ID = settings.development_parent_group_id

# Base URL for downloads.
DOWNLOAD_BASE = settings.download_base_url

# Maintenance download URL.
DOWNLOAD_MAINTENANCE = settings.download_maintenance

# AMQP server URL.
AMQP_URL = settings.amqp_url

OLDEST_APPROVAL_JOB_DAYS = settings.oldest_approval_job_days

# Limit for deprioritizing jobs.
DEPRIORITIZE_LIMIT = settings.deprioritize_limit

BASE_PRIO = settings.base_prio

# Scale factor for priority calculation.
PRIORITY_SCALE = settings.priority_scale

# Url of the "main" openQA server.
# This is only used to decide if the dashboard database should be updated or not.
# To change the openQA instance to talk to, use -i / --openqa-instance parameter.
OPENQA_URL = settings.main_openqa_domain

# User name of bot account that handles reviews.
# We need to ping this bot account to make reviews and reviews are requested for this account.
# See https://confluence.suse.com/spaces/~adrianSuSE/pages/1865908580/Group+Review+Bot+Setup#GroupReviewBotSetup-Suggestedgroupnames
GIT_REVIEW_BOT = settings.git_review_bot_user

BUILD_REGEX = (
    r"(?P<product>.*)-(?P<version>[^\-]*?)-(?P<flavor>\D+[^\-]*?)-(?P<arch>[^\-]*?)-Build(?P<build>.*?)\.spdx.json"
)

OBSOLETE_PARAMS = {
    "_OBSOLETE": "1",
    "_ONLY_OBSOLETE_SAME_BUILD": "1",
}
