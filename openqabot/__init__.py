# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# Used configuration parameters, e.g. api url's
QEM_DASHBOARD = "http://dashboard.qam.suse.de/"
SMELT = "https://smelt.suse.de/graphql"
OBS_URL = "https://api.suse.de"
OBS_MAINT_PRJ = "SUSE:Maintenance"
OBS_GROUP = "qam-openqa"
DEVELOPMENT_PARENT_GROUP_ID = 9
DOWNLOAD_BASE = "http://mirror.nue2.suse.org/ibs/SUSE:/Maintenance:/"
AMQP_URL = "amqps://suse:suse@rabbit.suse.de"
OLDEST_APPROVAL_JOB_DAYS = 6

# Url of the "main" openQA server, this is only used to decide if the dashboard database should be updated or not;
# to change the openQA instance to talk to, use -i / --openqa-instance parameter
OPENQA_URL = "openqa.suse.de"
