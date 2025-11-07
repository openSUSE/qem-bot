# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

import pathlib
from typing import Any, Callable, List
from unittest.mock import patch

import pytest

from openqabot.types import Data


@pytest.fixture
def mock_incident_settings_data_160() -> List[Data]:
    """Mock incident_settings_data with different Flavors in response"""
    pr_number = 160
    return [
        Data(
            incident=pr_number,
            settings_id=110,
            flavor="TestFlavor",
            arch="x86_64",
            distri="sle",
            version="15-SP7",
            build=":852:test",
            product="SLES",
        ),
        Data(
            incident=pr_number,
            settings_id=111,
            flavor="Server-DVD-Updates",
            arch="aarch64",
            distri="sle",
            version="15-SP6",
            build=":852:test",
            product="SLES",
        ),
    ]


@pytest.fixture
def mock_incident_settings_data_888() -> List[Data]:
    """Mock incident_settings_data with a single job"""
    pr_number = 888
    return [
        Data(
            incident=pr_number,
            settings_id=200,
            flavor="TestFlavor",
            arch="x86_64",
            distri="sle",
            version="15-SP6",
            build=":999:test",
            product="SLES",
        )
    ]


@pytest.fixture
def mock_qem_get_incident_settings() -> Any:
    """Fixture providing a mock for get_incident_settings_data function.
    To make it reusable across all tests append the patch with the other places
    you want to use it.

    Example:
        mock_qem_get_incident_settings.return_value = [Data(...), Data(...)]

    """
    with patch("openqabot.amqp.get_incident_settings_data") as mock_amqp:
        yield mock_amqp


@pytest.fixture
def mock_openqa_post_job() -> Any:
    """Fixture which mocks openQAInterface.post_job method.

    This fixture returns a context manager function that patches the post_job
    method on the openQAInterface class, making it generic and reusable.

    Usage:
        with mock_openqa_post_job(instance_with_client) as post_job:
            post_job.assert_called_once()
    """

    def _mock_post_job(instance_with_client: Any) -> Any:
        """Patch post_job on any instance that has a .client attribute"""
        return patch.object(instance_with_client.client, "post_job", return_value=None)

    return _mock_post_job


@pytest.fixture
def mock_gitea_review_request_body() -> Callable[[int], bytes]:
    """Return real Gitea AMQP webhook payload from fixture file.

    Args:
        pr_number: The pull request number

    Returns:
        callable: A function that accepts pr_number and returns bytes of the JSON payload

    Example:
        body = mock_gitea_review_request_body(160)

    """
    json_files = {
        160: "amqp-autogits_workflow_pr_bot-pull_request_review_approved-20251006-154156.json",
        888: "pull_request_review_requested_without_qam-openqa-review.json",
    }

    def _get_body(pr_number: int) -> bytes:
        """Load and return the JSON payload for the given PR number."""
        if pr_number not in json_files:
            raise ValueError(f"No fixture data available for PR number {pr_number}")

        review_request_path = pathlib.Path(__file__).parent / "gitea" / json_files[pr_number]
        with open(review_request_path, "rb") as f:
            return f.read()

    return _get_body
