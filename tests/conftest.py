# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
# fixtures modules to make them available to all tests
from tests.fixtures.qembot_mocks import (
    mock_gitea_review_request_body,
    mock_incident_make_incident_from_pr,
    mock_incident_settings_data_160,
    mock_incident_settings_data_888,
    mock_incident_settings_from_pr160,
    mock_incident_settings_from_pr888,
    mock_openqa_post_job,
    mock_qem_get_incident_settings,
)

__all__ = [
    "mock_gitea_review_request_body",
    "mock_incident_make_incident_from_pr",
    "mock_incident_settings_data_160",
    "mock_incident_settings_data_888",
    "mock_incident_settings_from_pr160",
    "mock_incident_settings_from_pr888",
    "mock_openqa_post_job",
    "mock_qem_get_incident_settings",
]
