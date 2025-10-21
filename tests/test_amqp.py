from collections import namedtuple
import logging
import json
from urllib.parse import urlparse
import responses
from openqabot.amqp import AMQP
from openqabot import QEM_DASHBOARD

namespace = namedtuple("Namespace", ["dry", "token", "openqa_instance", "url", "gitea_token"])
args = namespace(True, "ToKeN", urlparse("http://instance.qa"), None, None)
amqp = AMQP(args)

fake_method = namedtuple("Method", ["routing_key"])
fake_job_done = fake_method("suse.openqa.job.done")


@responses.activate
def test_handling_incident(caplog):
    # define response for get_incident_settings_data
    data = [
        {
            "id": 110,
            "flavor": "FakeFlavor",
            "arch": "arch",
            "settings": {"DISTRI": "linux", "BUILD": "33222"},
            "version": "13.3",
            "withAggregate": False,
        }
    ]
    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/incident_settings/33222",
        json=data,
    )

    # define response for get_aggregate_settings
    data = [
        {
            "id": 110,
            "flavor": "FakeFlavor",
            "arch": "arch",
            "settings": {"DISTRI": "linux", "BUILD": "33222"},
            "version": "13.3",
            "build": "33222",
        }
    ]
    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/update_settings/33222",
        json=data,
    )

    # define response for get_jobs
    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/jobs/incident/110",
        json=[{"incident_settings": 1000, "job_id": 110, "status": "passed"}],
    )

    # define incident
    responses.add(
        method="GET",
        url=f"{QEM_DASHBOARD}api/incidents/33222",
        json={"number": 33222, "rr_number": 42},
    )

    caplog.set_level(logging.DEBUG)
    amqp.on_message("", fake_job_done, "", json.dumps({"BUILD": ":33222:emacs"}))

    messages = [x[-1] for x in caplog.record_tuples]
    assert "Job for incident 33222 done" in messages
    assert "Incidents to approve:" in messages
    assert "* SUSE:Maintenance:33222:42" in messages


@responses.activate
def test_handling_aggregate(caplog):
    caplog.set_level(logging.DEBUG)
    amqp.on_message("", fake_job_done, "", json.dumps({"BUILD": "12345678-9"}))

    messages = [x[-1] for x in caplog.record_tuples]
    assert "Aggregate build 12345678-9 done" in messages  # currently noop
