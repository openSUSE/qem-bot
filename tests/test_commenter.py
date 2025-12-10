# tests/test_commenter.py
# Copyright SUSE LLC
# SPDX-License-Identifier: MIT

from argparse import Namespace

from openqabot.commenter import Commenter
from openqabot.errors import NoResultsError
from openqabot.types.incident import Incident
import pytest

from unittest.mock import MagicMock, Mock, patch

@pytest.fixture
def mock_args()->Namespace:
    return Namespace(dry=True, token="test_token")

@pytest.fixture
def mock_incident_smelt() -> Mock:
    mock_incident = Mock(spec=Incident)
    mock_incident.id = 1
    mock_incident.type = "smelt"
    return mock_incident

def test_commenter_init(mock_args: Namespace) -> None:
    mock_client = MagicMock()
    mock_incident = [MagicMock()]
    mock_commentapi = MagicMock()

    with (
        patch("openqabot.commenter.openQAInterface", return_value=mock_client),
        patch("openqabot.commenter.get_incidents", return_value=mock_incident),
        patch("openqabot.commenter.osc.conf.get_config"),
        patch("openqabot.commenter.CommentAPI", return_value=mock_commentapi),
        ):
            c = Commenter(mock_args)

    assert c.dry is True
    assert c.token == {"Authorization": f"Token test_token"}
    assert c.client is mock_client

def test_commenter_call(mock_args: Namespace, caplog: pytest.LogCaptureFixture) -> None:
    import logging
    caplog.set_level(logging.DEBUG)
    mock_incident = Mock(spec=Incident)
    mock_incident.id = 1
    mock_incident.type = "maintenance"

    with (
        patch("openqabot.commenter.openQAInterface"),
        patch("openqabot.commenter.get_incidents", return_value=[mock_incident]),
        patch("openqabot.commenter.osc.conf.get_config"),
        patch("openqabot.commenter.CommentAPI"),
    ):
        c = Commenter(mock_args)
        ret = c()
            
    assert ret == 0
    assert "Skipping incident 1 of type maintenance" in caplog.text

def test_commenter_call_value_error_incident_results(mock_args: Namespace, mock_incident_smelt: Mock, caplog: pytest.LogCaptureFixture) -> None:
    import logging
    caplog.set_level(logging.DEBUG)

    with (
        patch("openqabot.commenter.openQAInterface"),
        patch("openqabot.commenter.get_incidents", return_value=[mock_incident_smelt]),
        patch("openqabot.commenter.osc.conf.get_config"),
        patch("openqabot.commenter.CommentAPI"),
        patch("openqabot.commenter.get_incident_results", side_effect=ValueError("get_incident_results error")),
    ):
        c = Commenter(mock_args)
        ret = c()

    assert ret == 0
    assert "get_incident_results error" in caplog.text


def test_commenter_call_value_error_aggregate_results(mock_args: Namespace, mock_incident_smelt: Mock, caplog: pytest.LogCaptureFixture) -> None:
    import logging
    caplog.set_level(logging.DEBUG)

    with (
        patch("openqabot.commenter.openQAInterface"),
        patch("openqabot.commenter.get_incidents", return_value=[mock_incident_smelt]),
        patch("openqabot.commenter.osc.conf.get_config"),
        patch("openqabot.commenter.CommentAPI"),
        patch("openqabot.commenter.get_incident_results", return_value=0),
        patch("openqabot.commenter.get_aggregate_results", side_effect=ValueError("get_aggregate_results error")),
    ):
        c = Commenter(mock_args)
        ret = c()

    assert ret == 0
    assert "get_aggregate_results error" in caplog.text


def test_commenter_call_no_results_error_incident_results(mock_args: Namespace, mock_incident_smelt: Mock, caplog: pytest.LogCaptureFixture) -> None:
    import logging
    caplog.set_level(logging.DEBUG)

    with (
        patch("openqabot.commenter.openQAInterface"),
        patch("openqabot.commenter.get_incidents", return_value=[mock_incident_smelt]),
        patch("openqabot.commenter.osc.conf.get_config"),
        patch("openqabot.commenter.CommentAPI"),
        patch("openqabot.commenter.get_incident_results", side_effect=NoResultsError("No incident results")),
    ):
        c = Commenter(mock_args)
        ret = c()

    assert ret == 0
    assert "No incident results" in caplog.text

