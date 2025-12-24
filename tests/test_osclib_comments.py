# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from datetime import datetime
from io import BytesIO
from typing import Any, cast
from unittest.mock import patch

import pytest
from lxml import etree  # type: ignore[unresolved-import]
from pytest_mock import MockerFixture

from openqabot.osclib.comments import CommentAPI, OscCommentsEmptyError, OscCommentsValueError


def test_comment_as_dict() -> None:
    from openqabot.osclib.comments import _comment_as_dict  # noqa: PLC2701

    xml = etree.fromstring('<comment who="user" when="2022-01-01 12:00:00 UTC" id="1" parent="0">text</comment>')
    res = _comment_as_dict(xml)
    assert res["who"] == "user"
    assert isinstance(res["when"], datetime)
    assert res["id"] == "1"
    assert res["parent"] == "0"
    assert res["comment"] == "text"


def test_prepare_url() -> None:
    api = CommentAPI("https://api.opensuse.org")
    assert api._prepare_url(request_id="123") == "https://api.opensuse.org/comments/request/123"  # noqa: SLF001
    assert (
        api._prepare_url(project_name="proj", package_name="pkg")  # noqa: SLF001
        == "https://api.opensuse.org/comments/package/proj/pkg"
    )
    assert api._prepare_url(project_name="proj") == "https://api.opensuse.org/comments/project/proj"  # noqa: SLF001
    with pytest.raises(OscCommentsValueError):
        api._prepare_url()  # noqa: SLF001


def test_get_comments(mocker: MockerFixture) -> None:
    api = CommentAPI("https://api.opensuse.org")
    mock_get = mocker.patch("openqabot.osclib.comments.http_GET")
    xml_data = b'<comments><comment id="1" who="u" when="2022-01-01 12:00:00 UTC">c</comment></comments>'
    mock_get.return_value = BytesIO(xml_data)

    res = api.get_comments(request_id="123")
    assert len(res) == 1
    assert res["1"]["who"] == "u"


def test_comment_find() -> None:
    api = CommentAPI("https://api.opensuse.org")
    comments = {
        "1": {"comment": "<!-- bot key=val -->\ntext", "id": "1"},
        "2": {"comment": "manual comment", "id": "2"},
    }
    # find bot
    c, info = api.comment_find(comments, "bot")
    assert c["id"] == "1"
    assert info == {"key": "val"}

    # find with info match
    c, info = api.comment_find(comments, "bot", {"key": "val"})
    assert c["id"] == "1"

    # mismatch info
    c, info = api.comment_find(comments, "bot", {"key": "other"})
    assert c is None

    # mismatch info - key missing in info
    c, info = api.comment_find(comments, "bot", {"otherkey": "val"})
    assert c is None

    # no match
    c, info = api.comment_find(comments, "otherbot")
    assert c is None


def test_add_marker() -> None:
    res = CommentAPI.add_marker("text", "bot", {"k": "v"})
    assert "<!-- bot k=v -->" in res
    assert "text" in res


def test_add_marker_no_info() -> None:
    res = CommentAPI.add_marker("text", "bot")
    assert "<!-- bot -->" in res
    assert "text" in res


def test_add_comment(mocker: MockerFixture) -> None:
    api = CommentAPI("https://api.opensuse.org")
    mock_post = mocker.patch("openqabot.osclib.comments.http_POST", return_value="123")

    # empty comment
    with pytest.raises(OscCommentsEmptyError):
        api.add_comment(request_id="1", comment="")

    res = api.add_comment(request_id="1", comment="text")
    assert res == "123"
    mock_post.assert_called_once()


def test_truncate() -> None:
    assert CommentAPI.truncate("abc", length=3) == "abc"
    assert CommentAPI.truncate("abcd", length=3) == "abc"
    # test truncation length
    res = CommentAPI.truncate("very long comment", length=10)
    assert len(res) <= 10
    # pre tags - just check it doesn't crash and returns something within length
    res = CommentAPI.truncate("<pre>code</pre>", length=10)
    assert len(res) <= 17  # length + suffix + \n</pre>


def test_truncate_long() -> None:
    api = CommentAPI("https://api.url")
    long_msg = "a" * 2000
    res = api.truncate(long_msg, length=1000)
    assert len(res) <= 1000
    assert res.endswith("...")


def test_comment_find_no_match() -> None:
    api = CommentAPI("https://api.url")
    comments = {1: {"comment": "not a bot comment", "id": 1}}
    c, info = api.comment_find(comments, "bot")
    assert c is None
    assert info is None


def test_comment_find_wrong_bot() -> None:
    api = CommentAPI("https://api.url")
    comments = {1: {"comment": "<!-- otherbot -->", "id": 1}}
    c, info = api.comment_find(comments, "bot")
    assert c is None
    assert info is None


def test_truncate_very_short() -> None:
    api = CommentAPI("https://api.url")
    assert api.truncate("some long comment", length=5) == "some "


def test_truncate_near_closing_pre() -> None:
    api = CommentAPI("https://api.url")
    msg = "text <pre>code</pre> more"
    # end near </pre> (index 15)
    res = api.truncate(msg, length=18)
    assert res == "text ..."


def test_delete_children_complex() -> None:
    api = CommentAPI("https://api.url")
    comments = {
        "1": {"id": "1", "parent": None, "who": "nobody"},
        "2": {"id": "2", "parent": "1", "who": "user"},
    }
    with patch("openqabot.osclib.comments.http_DELETE"):
        res = api.delete_children(comments)
    # 1 is a parent, so it's not deleted.
    # 2 has no children, so it's deleted.
    assert "1" in res
    assert "2" not in res


def test_delete(mocker: MockerFixture) -> None:
    api = CommentAPI("https://api.opensuse.org")
    mock_delete = mocker.patch("openqabot.osclib.comments.http_DELETE")
    api.delete("1")
    mock_delete.assert_called_once()


def test_delete_children(mocker: MockerFixture) -> None:
    api = CommentAPI("https://api.opensuse.org")
    mocker.patch.object(api, "delete")
    comments = {"1": {"id": "1", "parent": None, "who": "u"}, "2": {"id": "2", "parent": "1", "who": "u"}}
    res = api.delete_children(comments)
    cast("Any", api.delete).assert_called_with("2")
    assert "2" not in res
    assert "1" in res


def test_delete_from(mocker: MockerFixture) -> None:
    api = CommentAPI("https://api.opensuse.org")
    mocker.patch.object(api, "get_comments", side_effect=[{"1": {"id": "1", "parent": None, "who": "u"}}, {}])
    mocker.patch.object(api, "delete_children", return_value={})
    api.delete_from(request_id="1")
    cast("Any", api.get_comments).assert_called()


def test_delete_from_where_user(mocker: MockerFixture) -> None:
    api = CommentAPI("https://api.opensuse.org")
    mocker.patch.object(api, "get_comments", return_value={"1": {"id": "1", "who": "user"}})
    mocker.patch.object(api, "delete")
    api.delete_from_where_user("user", request_id="1")
    cast("Any", api.delete).assert_called_once_with("1")


def test_comment_find_empty_info() -> None:
    api = CommentAPI("https://api.url")
    comments = {
        "1": {"comment": "<!-- bot -->", "id": "1"},
    }
    c, info = api.comment_find(comments, "bot")
    assert c["id"] == "1"
    assert info == {}


def test_add_comment_with_parent(mocker: MockerFixture) -> None:
    api = CommentAPI("https://api.url")
    mock_post = mocker.patch("openqabot.osclib.comments.http_POST", return_value="123")
    api.add_comment(request_id="1", comment="msg", parent_id="99")
    assert mock_post.called


def test_truncate_unbalanced_pre() -> None:
    api = CommentAPI("https://api.url")
    # more <pre> than </pre>, and length triggers truncation
    msg = "<pre>some very long code block"
    res = api.truncate(msg, length=15)
    # length 15 - suffix 3 = 12. <pre> found, so end -= 7 -> 5.
    assert res == "<pre>...\n</pre>"


def test_comment_find_mismatch_info() -> None:
    api = CommentAPI("https://api.url")
    comments = {
        "1": {"comment": "<!-- bot k1=v1 -->", "id": "1"},
    }
    # key not in info
    c, info = api.comment_find(comments, "bot", {"k2": "v2"})
    assert c is None
    assert info is None

    # value mismatch
    c, info = api.comment_find(comments, "bot", {"k1": "v2"})
    assert c is None
    assert info is None


def test_delete_children_nobody(mocker: MockerFixture) -> None:
    api = CommentAPI("https://api.url")
    mocker.patch.object(api, "delete")
    comments = {
        "1": {"id": "1", "parent": None, "who": "_nobody_"},
    }
    res = api.delete_children(comments)
    assert "1" not in res
    cast("Any", api.delete).assert_not_called()


def test_delete_from_where_user_mismatch(mocker: MockerFixture) -> None:
    api = CommentAPI("https://api.url")
    mocker.patch.object(api, "get_comments", return_value={"1": {"id": "1", "who": "other"}})
    mocker.patch.object(api, "delete")
    api.delete_from_where_user("user", request_id="1")
    cast("Any", api.delete).assert_not_called()
