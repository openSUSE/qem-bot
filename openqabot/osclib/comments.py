# Copyright SUSE LLC
# SPDX-License-Identifier: GPL-2.0+
import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple, Union
from xml.etree import ElementTree as ET

from osc.core import http_DELETE, http_GET, http_POST, makeurl

from openqabot.utc import UTC


def _comment_as_dict(comment_element: ET.Element) -> Dict[str, Any]:
    """Convert an XML element comment into a dictionary.

    :param comment_element: XML element that store a comment.
    :returns: A Python dictionary object.
    """
    return {
        "who": comment_element.get("who"),
        "when": datetime.strptime(comment_element.get("when"), "%Y-%m-%d %H:%M:%S %Z").astimezone(UTC),
        "id": comment_element.get("id"),
        "parent": comment_element.get("parent", None),
        "comment": comment_element.text,
    }


class CommentAPI(object):
    COMMENT_MARKER_REGEX = re.compile(r"<!-- (?P<bot>[^ ]+)(?P<info>(?: [^= ]+=[^ ]+)*) -->")

    def __init__(self, apiurl: str) -> None:
        self.apiurl = apiurl

    def _prepare_url(
        self,
        request_id: Optional[Union[str, int]] = None,
        project_name: Optional[str] = None,
        package_name: Optional[str] = None,
        query: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Prepare the URL to get/put comments in OBS.

        :param request_id: Request where to refer the comment.
        :param project_name: Project name where to refer comment.
        :param package_name: Package name where to refer the comment.
        :returns: Formated URL for the request.
        """
        url = None
        if request_id:
            url = makeurl(self.apiurl, ["comments", "request", request_id], query)
        elif project_name and package_name:
            url = makeurl(self.apiurl, ["comments", "package", project_name, package_name], query)
        elif project_name:
            url = makeurl(self.apiurl, ["comments", "project", project_name], query)
        else:
            msg = "Please, set request_id, project_name or / and package_name to add a comment."
            raise ValueError(msg)
        return url

    def get_comments(
        self,
        request_id: Optional[Union[str, int]] = None,
        project_name: Optional[str] = None,
        package_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get the list of comments of an object in OBS.

        :param request_id: Request where to get comments.
        :param project_name: Project name where to get comments.
        :param package_name: Package name where to get comments.
        :returns: A list of comments (as a dictionary).
        """
        url = self._prepare_url(request_id, project_name, package_name)
        root = ET.parse(http_GET(url)).getroot()
        comments = {}
        for c in root.findall("comment"):
            c = _comment_as_dict(c)
            comments[c["id"]] = c
        return comments

    def comment_find(
        self,
        comments: Dict[str, Any],
        bot: str,
        info_match: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        """Return previous bot comments that match criteria."""
        # Case-insensitive for backwards compatibility.
        bot = bot.lower()
        for c in list(comments.values()):
            m = self.COMMENT_MARKER_REGEX.match(c["comment"])
            if m and bot == m.group("bot").lower():
                info = {}

                # Python base regex does not support repeated subgroup capture
                # so parse the optional info using string split.
                stripped = m.group("info").strip()
                if stripped:
                    for pair in stripped.split(" "):
                        key, value = pair.split("=")
                        info[key] = value

                # Skip if info does not match.
                if info_match:
                    match = True
                    for key, value in list(info_match.items()):
                        if not (value is None or (key in info and info[key] == value)):
                            match = False
                            break
                    if not match:
                        continue

                return c, info
        return None, None

    @staticmethod
    def add_marker(comment: str, bot: str, info: Optional[Dict[str, Any]] = None) -> str:
        """Add bot marker to comment that can be used to find comment."""
        if info:
            infos = []
            for key, value in info.items():
                infos.append("=".join((str(key), str(value))))

        marker = "<!-- {}{} -->".format(bot, " " + " ".join(infos) if info else "")
        return marker + "\n\n" + comment

    def add_comment(
        self,
        request_id: Optional[Union[str, int]] = None,
        project_name: Optional[str] = None,
        package_name: Optional[str] = None,
        comment: Optional[str] = None,
        parent_id: Optional[Union[str, int]] = None,
    ) -> str:
        """Add a comment in an object in OBS.

        :param request_id: Request where to write a comment.
        :param project_name: Project name where to write a comment.
        :param package_name: Package name where to write a comment.
        :param comment: Comment to be published.
        :return: Comment id.
        """
        if not comment:
            msg = "Empty comment."
            raise ValueError(msg)

        comment = self.truncate(comment.strip())

        query = {}
        if parent_id:
            query["parent_id"] = parent_id
        url = self._prepare_url(request_id, project_name, package_name, query)
        return http_POST(url, data=comment)

    @staticmethod
    def truncate(comment: str, suffix: str = "...", length: int = 65535) -> str:
        # Handle very short length by dropping suffix and just chopping comment.
        if length <= len(suffix) + len("\n</pre>"):
            return comment[:length]
        if len(comment) <= length:
            return comment

        # Determine the point at which to end by leaving room for suffix.
        end = length - len(suffix)
        if comment.find("<pre>", 0, end) != -1:
            # For the sake of simplicity leave space for closing pre tag even if
            # after truncation it may no longer be necessary. Otherwise, it
            # requires recursion with some fun edge cases.
            end -= len("\n</pre>")

        # Check for the end location landing inside a pre tag and correct by
        # moving in front of the tag. Landing on the ends is a noop.
        pre_index = max(
            comment.rfind("<pre>", end - 4, end + 4),
            comment.rfind("</pre>", end - 5, end + 5),
        )
        if pre_index != -1:
            end = pre_index

        comment = comment[:end]

        # Check for unbalanced pre tag and add a closing tag.
        if comment.count("<pre>") > comment.count("</pre>"):
            suffix += "\n</pre>"

        return comment + suffix

    def delete(self, comment_id: Union[str, int]) -> None:
        """Remove a comment object.

        :param comment_id: Id of the comment object.
        """
        url = makeurl(self.apiurl, ["comment", comment_id])
        http_DELETE(url)

    def delete_children(self, comments: Dict[str, Any]) -> Dict[str, Any]:
        """Remove the comments that have no childs.

        :param comments dict of id->comment dict
        :return same hash without the deleted comments
        """
        parents = [comment["parent"] for comment in comments.values() if comment["parent"]]

        for comment in list(comments.values()):
            if comment["id"] not in parents:
                # Parent comments that have been removed are still returned
                # when children exist and are authored by _nobody_. Such
                # should not be deleted remotely, but only marked internally.
                if comment["who"] != "_nobody_":
                    self.delete(comment["id"])
                del comments[comment["id"]]

        return comments

    def delete_from(
        self,
        request_id: Optional[Union[str, int]] = None,
        project_name: Optional[str] = None,
        package_name: Optional[str] = None,
    ) -> bool:
        """Remove the comments related with a request, project or package.

        :param request_id: Request where to remove comments.
        :param project_name: Project name where to remove comments.
        :param package_name: Package name where to remove comments.
        :return: Number of comments removed.
        """
        comments = self.get_comments(request_id, project_name, package_name)
        while comments:
            comments = self.delete_children(comments)
        return True

    def delete_from_where_user(
        self,
        user: str,
        request_id: Optional[Union[str, int]] = None,
        project_name: Optional[str] = None,
        package_name: Optional[str] = None,
    ) -> None:
        """Remove comments where @user is mentioned.

        This method is used to remove notifications when a request is
        removed or moved to another project.
        :param user: User name where the comment will be removed.
        :param request_id: Request where to remove comments.
        :param project_name: Project name where to remove comments.
        :param package_name: Package name where to remove comments.
        :return: Number of comments removed.
        """
        for comment in list(self.get_comments(request_id, project_name, package_name).values()):
            if comment["who"] == user:
                self.delete(comment["id"])
