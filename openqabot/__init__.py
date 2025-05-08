# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

import os

# Used configuration parameters, e.g. api url's
QEM_DASHBOARD = os.environ.get("QEM_DASHBOARD_URL", "http://dashboard.qam.suse.de/")
SMELT = os.environ.get("SMELT_URL", "https://smelt.suse.de/graphql")
GITEA = os.environ.get("GITEA_URL", "https://src.suse.de")
OBS_URL = os.environ.get("OBS_URL", "https://api.suse.de")
OBS_MAINT_PRJ = "SUSE:Maintenance"
OBS_GROUP = "qam-openqa"
DEVELOPMENT_PARENT_GROUP_ID = 9
DOWNLOAD_BASE = os.environ.get(
    "DOWNLOAD_BASE_URL", "http://%REPO_MIRROR_HOST%/ibs/SUSE:/Maintenance:/"
)
AMQP_URL = os.environ.get("AMQP_URL", "amqps://suse:suse@rabbit.suse.de")
OLDEST_APPROVAL_JOB_DAYS = 6

# Url of the "main" openQA server, this is only used to decide if the dashboard database should be updated or not;
# to change the openQA instance to talk to, use -i / --openqa-instance parameter
OPENQA_URL = "openqa.suse.de"
