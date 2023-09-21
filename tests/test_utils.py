import pytest
import responses
from pathlib import Path

# responses versions older than
# https://github.com/getsentry/responses/releases/tag/0.17.0
# do not have "registries" so we need to skip on older versions
has_registries = False
try:
    from responses import registries

    has_registries = True
except ImportError as e:
    import logging

    logging.info(str(e) + ": Likely older python version")

from openqabot.utils import walk, normalize_results, retry3, get_yml_list


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


def test_get_yml_list_single_file_yml(tmp_path):
    """
    Create a folder with a single .yml file
    Call the function with the path of the file
    The expected behavior is the function to return
    a single element list with the file Path
    """
    for ext in ("yml", "yaml"):
        d = tmp_path / f"it_is_a_folder_for_{ext}"
        d.mkdir()
        filename = f"hello.{ext}"
        p = d / filename
        p.write_text("")
        # here call the function with the file path
        res = get_yml_list(Path(p))
        assert len(res) == 1
        assert filename in res[0].name


def test_get_yml_list_single_file_not_yml(tmp_path):
    """
    Create a folder with a single .txt file (so not a supported valid file)
    Call the function with the path of the file
    The expected behavior is the function to return
    an empty list
    """
    d = tmp_path / "it_is_a_folder"
    d.mkdir()
    p = d / "hello.txt"
    p.write_text("")
    # here call the function with the file path
    res = get_yml_list(Path(p))
    assert len(res) == 0


def test_get_yml_list_folder_with_single_file_yml(tmp_path):
    d = tmp_path / "it_is_a_folder"
    d.mkdir()
    p = d / "hello.yml"
    p.write_text("")
    # here call the function with the folder and not with file like in previous tests
    res = get_yml_list(Path(d))
    assert len(res) == 1
    assert "hello.yml" in res[0].name


def test_get_yml_list_folder_with_multiple_files(tmp_path):
    """
    Create a folder with 10 files in it, 5 has a valid extension
    """
    d = tmp_path / "it_is_a_folder"
    d.mkdir()
    for ext in ("txt", "yml", "yaml"):
        for _ in range(5):
            p = d / f"hello{_}.{ext}"
            p.write_text(f"Content {_}")
    # here call the function with the folder
    res = get_yml_list(Path(d))
    # only 5 yml + 5 yaml files over 15 total files
    assert len(res) == 10
