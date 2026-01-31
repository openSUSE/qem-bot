# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Configuration constants."""

import os

# Used configuration parameters, e.g. api url's
QEM_DASHBOARD = os.environ.get("QEM_DASHBOARD_URL", "http://dashboard.qam.suse.de/")
DEFAULT_SUBMISSION_TYPE = "smelt"
SMELT_URL = os.environ.get("SMELT_URL", "https://smelt.suse.de")
SMELT = SMELT_URL + "/graphql"
GITEA = os.environ.get("GITEA_URL", "https://src.suse.de")
OBS_URL = os.environ.get("OBS_URL", "https://api.suse.de")
OBS_DOWNLOAD_URL = os.environ.get("OBS_DOWNLOAD_URL", "http://download.suse.de/ibs")
OBS_MAINT_PRJ = "SUSE:Maintenance"
OBS_GROUP = "qam-openqa"
OBS_REPO_TYPE = os.environ.get("OBS_REPO_TYPE", "product")
OBS_PRODUCTS = set(os.environ.get("OBS_PRODUCTS", "all").split(","))
ALLOW_DEVELOPMENT_GROUPS = os.environ.get("QEM_BOT_ALLOW_DEVELOPMENT_GROUPS")
DEVELOPMENT_PARENT_GROUP_ID = 9
DOWNLOAD_BASE = os.environ.get("DOWNLOAD_BASE_URL", "http://%REPO_MIRROR_HOST%/ibs")
DOWNLOAD_MAINTENANCE = os.environ.get("DOWNLOAD_MAINTENANCE_BASE_URL", DOWNLOAD_BASE + "/SUSE:/Maintenance:/")
AMQP_URL = os.environ.get("AMQP_URL", "amqps://suse:suse@rabbit.suse.de")
OLDEST_APPROVAL_JOB_DAYS = 6
DEPRIORITIZE_LIMIT = os.environ.get("QEM_BOT_DEPRIORITIZE_LIMIT", None)
BASE_PRIO = 50
PRIORITY_SCALE = int(os.environ.get("QEM_BOT_PRIORITY_SCALE", "20"))

# Url of the "main" openQA server, this is only used to decide if the dashboard database should be updated or not;
# to change the openQA instance to talk to, use -i / --openqa-instance parameter
OPENQA_URL = os.environ.get("MAIN_OPENQA_DOMAIN", "openqa.suse.de")

# user name of bot account that handles reviews
# We need to ping this bot account to make reviews and reviews are requested for
# this account, see
# https://confluence.suse.com/spaces/~adrianSuSE/pages/1865908580/Group+Review+Bot+Setup#GroupReviewBotSetup-Suggestedgroupnames
GIT_REVIEW_BOT = os.environ.get("GIT_REVIEW_BOT", OBS_GROUP + "-review")

BUILD_REGEX = (
    r"(?P<product>.*)-(?P<version>[^\-]*?)-(?P<flavor>\D+[^\-]*?)-(?P<arch>[^\-]*?)-Build(?P<build>.*?)\.spdx.json"
)

OBSOLETE_PARAMS = {
    "_OBSOLETE": "1",
    "_ONLY_OBSOLETE_SAME_BUILD": "1",
}
