# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Configuration constants.

This module defines configuration constants used throughout the application.
Most of these constants can be overridden by environment variables.
"""

import os

# Used configuration parameters, e.g. api url's
# Dashboard URL.
QEM_DASHBOARD = os.environ.get("QEM_DASHBOARD_URL", "http://dashboard.qam.suse.de/")
DEFAULT_SUBMISSION_TYPE = "smelt"

# SMELT URL.
SMELT_URL = os.environ.get("SMELT_URL", "https://smelt.suse.de")
SMELT = SMELT_URL + "/graphql"

# Gitea URL.
GITEA = os.environ.get("GITEA_URL", "https://src.suse.de")

# OBS API URL.
OBS_URL = os.environ.get("OBS_URL", "https://api.suse.de")

# OBS Download URL (IBS).
OBS_DOWNLOAD_URL = os.environ.get("OBS_DOWNLOAD_URL", "http://download.suse.de/ibs")

OBS_MAINT_PRJ = "SUSE:Maintenance"
OBS_GROUP = "qam-openqa"

# Type of the repository for OBS/IBS.
OBS_REPO_TYPE = os.environ.get("OBS_REPO_TYPE", "product")

# OBS products to consider.
OBS_PRODUCTS = set(os.environ.get("OBS_PRODUCTS", "all").split(","))

# Allow scheduling in development groups.
ALLOW_DEVELOPMENT_GROUPS = os.environ.get("QEM_BOT_ALLOW_DEVELOPMENT_GROUPS")
DEVELOPMENT_PARENT_GROUP_ID = 9

# Base URL for downloads.
DOWNLOAD_BASE = os.environ.get("DOWNLOAD_BASE_URL", "http://%REPO_MIRROR_HOST%/ibs")

# Maintenance download URL.
DOWNLOAD_MAINTENANCE = os.environ.get("DOWNLOAD_MAINTENANCE_BASE_URL", DOWNLOAD_BASE + "/SUSE:/Maintenance:/")

# AMQP server URL.
AMQP_URL = os.environ.get("AMQP_URL", "amqps://suse:suse@rabbit.suse.de")

OLDEST_APPROVAL_JOB_DAYS = 6

# Limit for deprioritizing jobs.
# If set, this value controls the priority calculation for openQA jobs.
# If the number of jobs in a job group exceeds this limit, new jobs will be assigned a lower
# priority. This prevents maintenance jobs from flooding the queue and blocking other
# important tests.
DEPRIORITIZE_LIMIT = os.environ.get("QEM_BOT_DEPRIORITIZE_LIMIT", None)

BASE_PRIO = 50

# Scale factor for priority calculation.
# Used to adjust the job priority.
PRIORITY_SCALE = int(os.environ.get("QEM_BOT_PRIORITY_SCALE", "20"))

# Url of the "main" openQA server.
# This is only used to decide if the dashboard database should be updated or not.
# To change the openQA instance to talk to, use -i / --openqa-instance parameter.
OPENQA_URL = os.environ.get("MAIN_OPENQA_DOMAIN", "openqa.suse.de")

# User name of bot account that handles reviews.
# We need to ping this bot account to make reviews and reviews are requested for this account.
# See https://confluence.suse.com/spaces/~adrianSuSE/pages/1865908580/Group+Review+Bot+Setup#GroupReviewBotSetup-Suggestedgroupnames
GIT_REVIEW_BOT = os.environ.get("GIT_REVIEW_BOT", OBS_GROUP + "-review")

BUILD_REGEX = (
    r"(?P<product>.*)-(?P<version>[^\-]*?)-(?P<flavor>\D+[^\-]*?)-(?P<arch>[^\-]*?)-Build(?P<build>.*?)\.spdx.json"
)

OBSOLETE_PARAMS = {
    "_OBSOLETE": "1",
    "_ONLY_OBSOLETE_SAME_BUILD": "1",
}
