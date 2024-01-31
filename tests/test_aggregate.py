from openqabot.types.aggregate import Aggregate
from openqabot.types.incidents import Incident
from openqabot.loader.repohash import get_max_revision
import pytest
from logging import getLogger

logger = getLogger(__name__)


def test_aggregate_constructor():
    """
    What is the bare minimal set of arguments
    needed by the constructor?
    """
    config = {}
    config["FLAVOR"] = "None"
    config["archs"] = None
    config["test_issues"] = {}
    acc = Aggregate("", None, config)


def test_aggregate_printable():
    """
    Try the printable
    """
    config = {}
    config["FLAVOR"] = "None"
    config["archs"] = None
    config["test_issues"] = {}
    acc = Aggregate("hello", None, config)
    assert "<Aggregate product: hello>" == str(acc)


def test_aggregate_call():
    """
    What is the bare minimal set of arguments
    needed by the callable?
    """
    config = {}
    config["FLAVOR"] = "None"
    config["archs"] = []
    config["test_issues"] = {}
    acc = Aggregate("", None, config)
    res = acc(None, None, None)
    assert res == []


@pytest.fixture
def request_mock(monkeypatch):
    """
    Aggregate is using requests to get old jobs
    from the QEM dashboard.
    At the moment the mock returned value
    is harcoded to [{}]
    """

    class MockResponse:
        # mock json() method always returns a specific testing dictionary
        @staticmethod
        def json():
            return [{}]

    def mock_get(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr(
        "openqabot.dashboard.requests.get",
        mock_get,
    )


def test_aggregate_call_with_archs(request_mock):
    """
    Configure an archs to enter in the function main loop
    """
    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {}
    acc = Aggregate("", settings={}, config=my_config)
    res = acc(incidents=[], token=None, ci_url=None)
    assert res == []


@pytest.fixture
def incident_mock(monkeypatch):
    """
    Simulate an incident class, reimplementing it in the simplest
    possible way that is accepted by Aggregate
    """
    from typing import NamedTuple

    class Repos(NamedTuple):
        product: str
        version: str
        arch: str

    class MockIncident:
        def __init__(self, repo, embargoed, mocked_incident=42):
            self.id = mocked_incident
            self.livepatch = None
            self.staging = None
            self.channels = [repo]
            self.embargoed = embargoed
            self._has_failures = False

        def has_failures(self, token):
            does_it_have_failures = self.id == 666 or self._has_failures
            logger.debug(
                "incident %s, has_failures = %s",
                self,
                does_it_have_failures,
            )
            return does_it_have_failures

        def __repr__(self):
            return f"<MockIncident id: {self.id} with repos {self.channels}>"

    def _func(product, version, arch, embargoed=False, mocked_incident=42):
        repo = Repos(product=product, version=version, arch=arch)
        return MockIncident(repo, embargoed=embargoed, mocked_incident=mocked_incident)

    return _func


def _check_assert_incident(response, expected_count: int):
    for list_of_incidents in response:
        count_incidents = lambda x: len(x["qem"]["incidents"])
        logger.debug("incident: %s", print(list_of_incidents))
        assert expected_count == count_incidents(list_of_incidents)


def test_aggregate_call_with_test_issues(
    request_mock, incident_mock, monkeypatch, caplog
):
    """
    Test with a valid incident
    """

    caplog.set_level("DEBUG")

    my_config = {}
    my_config["FLAVOR"] = "Habanero"
    my_config["archs"] = ["ciao", "aarch64"]
    my_config["test_issues"] = {"AAAAAAA": "BBBBBBBBB:CCCCCCCC"}
    my_config["product"] = "openQA"
    acc = Aggregate("", settings={}, config=my_config)

    these_incidents = []
    good_incident = incident_mock(
        product="BBBBBBBBB", version="CCCCCCCC", arch="ciao", mocked_incident=1284
    )
    logger.info("Testing the the_good_incident")
    these_incidents.append(good_incident)

    res = acc(
        these_incidents,
        token=None,
        ci_url=None,
    )

    _check_assert_incident(res, 1)  # the good incident is good

    the_demon_incident = incident_mock(
        product="BBBBBBBBB", version="CCCCCCCC", arch="ciao", mocked_incident=666
    )
    logger.info("Testing the the_demon_incident")
    these_incidents.append(the_demon_incident)

    res = acc(
        these_incidents,
        token=None,
        ci_url=None,
    )

    _check_assert_incident(res, 1)  # the demon incident must be banished

    the_moved_incident = incident_mock(
        product="BBBBBBBBB", version="CCCCCCCC", arch="ciao", mocked_incident=1335
    )
    these_incidents.append(the_moved_incident)
    logger.info("Testing the the_moved_incident (%s)", len(res))

    res = acc(
        these_incidents,
        token=None,
        ci_url=None,
    )

    assert len(these_incidents) == 3  # banished doesn't mean gone
    _check_assert_incident(res, 2)  # the moved incident decides not to leave


def test_aggregate_call_pc_pint(request_mock, monkeypatch):
    """
    Test with setting PUBLIC_CLOUD_PINT_QUERY to call apply_publiccloud_pint_image
    """

    def mockreturn(settings):
        return {"PUBLIC_CLOUD_IMAGE_ID": "Hola"}

    monkeypatch.setattr(
        "openqabot.types.aggregate.apply_publiccloud_pint_image",
        mockreturn,
    )

    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {}
    my_settings = {"PUBLIC_CLOUD_PINT_QUERY": None}
    acc = Aggregate("", settings=my_settings, config=my_config)
    acc(incidents=[], token=None, ci_url=None)


def test_aggregate_call_pc_pint_with_incidents(
    request_mock, incident_mock, monkeypatch
):
    """
    Test with incident and setting PUBLIC_CLOUD_PINT_QUERY to call apply_publiccloud_pint_image
    """

    def mockreturn(settings):
        return {"PUBLIC_CLOUD_IMAGE_ID": "Hola"}

    monkeypatch.setattr(
        "openqabot.types.aggregate.apply_publiccloud_pint_image",
        mockreturn,
    )
    my_config = {}
    my_config["FLAVOR"] = "None"
    my_config["archs"] = ["ciao"]
    my_config["test_issues"] = {"AAAAAAA": "BBBBBBBBB:CCCCCCCC"}
    my_settings = {"PUBLIC_CLOUD_PINT_QUERY": None}
    acc = Aggregate("", settings=my_settings, config=my_config)
    ret = acc(
        incidents=[incident_mock(product="BBBBBBBBB", version="CCCCCCCC", arch="ciao")],
        token=None,
        ci_url=None,
    )
    assert ret[0]["openqa"]["PUBLIC_CLOUD_IMAGE_ID"] == "Hola"
