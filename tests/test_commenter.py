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
