import pytest

from openqabot.utils import walk, normalize_results


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
