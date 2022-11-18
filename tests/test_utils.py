import pytest
import responses

has_registries = False
try:
    from responses import registries

    has_registries = True
except ImportError as e:
    import logging

    logging.info(str(e) + ": Likely older python version")

from openqabot.utils import walk, normalize_results, retry3


def test_normalize_results():
    assert normalize_results("none") == "waiting"
    assert normalize_results("passed") == "passed"
    assert normalize_results("failed") == "failed"
    assert normalize_results("something") == "failed"
    assert normalize_results("softfailed") == "passed"
    for result in (
        "timeout_exceeded",
        "incomplete",
        "obsoleted",
        "parallel_failed",
        "skipped",
        "parallel_restarted",
        "user_cancelled",
        "user_restarted",
    ):
        assert normalize_results(result) == "stopped"


@pytest.mark.parametrize(
    "data,result",
    [
        ([], []),
        ({}, {}),
        (
            {
                "d": {
                    "i": {
                        "edges": [
                            {
                                "node": {
                                    "rS": {"edges": []},
                                    "p": {"edges": [{"node": {"name": "ra"}}]},
                                    "r": {
                                        "edges": [
                                            {"node": {"name": "12:x86_64"}},
                                            {"node": {"name": "12:Update"}},
                                            {"node": {"name": "12:s390x"}},
                                        ]
                                    },
                                    "c": {"edges": []},
                                    "cM": None,
                                    "cQ": None,
                                }
                            }
                        ]
                    }
                }
            },
            {
                "d": {
                    "i": [
                        {
                            "cM": None,
                            "cQ": None,
                            "c": [],
                            "p": [{"name": "ra"}],
                            "r": [
                                {"name": "12:x86_64"},
                                {"name": "12:Update"},
                                {"name": "12:s390x"},
                            ],
                            "rS": [],
                        }
                    ]
                },
            },
        ),
    ],
)
def test_walk(data, result):
    ret = walk(data)
    assert result == ret


if has_registries:

    @responses.activate(registry=registries.OrderedRegistry)
    def test_retry3():
        rsp1 = responses.add(responses.GET, "http://host.some", status=503)
        rsp2 = responses.add(responses.GET, "http://host.some", status=503)
        rsp3 = responses.add(responses.GET, "http://host.some", status=200)

        req = retry3.get("http://host.some")
        assert req.status_code == 200
        assert rsp3.call_count == 1
