# Copyright SUSE LLC
# SPDX-License-Identifier: GPL-2.0+
from datetime import datetime
import re
from xml.etree import ElementTree as ET

from osc.core import http_DELETE
from osc.core import http_GET
from osc.core import http_POST
from osc.core import makeurl


def _comment_as_dict(comment_element):
    """Convert an XML element comment into a dictionary.

    :param comment_element: XML element that store a comment.
    :returns: A Python dictionary object.
    """
    comment = {
        "who": comment_element.get("who"),
        "when": datetime.strptime(comment_element.get("when"), "%Y-%m-%d %H:%M:%S %Z"),
        "id": comment_element.get("id"),
        "parent": comment_element.get("parent", None),
        "comment": comment_element.text,
    }
    return comment


class CommentAPI(object):
    COMMENT_MARKER_REGEX = re.compile(
        r"<!-- (?P<bot>[^ ]+)(?P<info>(?: [^= ]+=[^ ]+)*) -->"
    )

    def __init__(self, apiurl):
        self.apiurl = apiurl

    def _prepare_url(
        self, request_id=None, project_name=None, package_name=None, query=None
    ):
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
            url = makeurl(
                self.apiurl, ["comments", "package", project_name, package_name], query
            )
        elif project_name:
            url = makeurl(self.apiurl, ["comments", "project", project_name], query)
        else:
            raise ValueError(
                "Please, set request_id, project_name or / and package_name to add a comment."
            )
        return url

    def get_comments(self, request_id=None, project_name=None, package_name=None):
        """Get the list of comments of an object in OBS.

        :param request_id: Request where to get comments.
        :param project_name: Project name where to get comments.
        :param package_name: Package name where to get comments.
        :returns: A list of comments (as a dictionary).
        """
        url = self._prepare_url(request_id, project_name, package_name)
        root = root = ET.parse(http_GET(url)).getroot()
        comments = {}
        for c in root.findall("comment"):
            c = _comment_as_dict(c)
            comments[c["id"]] = c
        return comments

    def comment_find(self, comments, bot, info_match=None):
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
    def add_marker(comment, bot, info=None):
        """Add bot marker to comment that can be used to find comment."""
        if info:
            infos = []
            for key, value in info.items():
                infos.append("=".join((str(key), str(value))))

        marker = "<!-- {}{} -->".format(bot, " " + " ".join(infos) if info else "")
        return marker + "\n\n" + comment

    def add_comment(
        self,
        request_id=None,
        project_name=None,
        package_name=None,
        comment=None,
        parent_id=None,
    ):
        """Add a comment in an object in OBS.

        :param request_id: Request where to write a comment.
        :param project_name: Project name where to write a comment.
        :param package_name: Package name where to write a comment.
        :param comment: Comment to be published.
        :return: Comment id.
        """
        if not comment:
            raise ValueError("Empty comment.")

        comment = self.truncate(comment.strip())

        query = {}
        if parent_id:
            query["parent_id"] = parent_id
        url = self._prepare_url(request_id, project_name, package_name, query)
        return http_POST(url, data=comment)

    @staticmethod
    def truncate(comment, suffix="...", length=65535):
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

    def delete(self, comment_id):
        """Remove a comment object.

        :param comment_id: Id of the comment object.
        """
        url = makeurl(self.apiurl, ["comment", comment_id])
        return http_DELETE(url)

    def delete_children(self, comments):
        """Remove the comments that have no childs.

        :param comments dict of id->comment dict
        :return same hash without the deleted comments
        """
        parents = []
        for comment in list(comments.values()):
            if comment["parent"]:
                parents.append(comment["parent"])

        for comment in list(comments.values()):
            if comment["id"] not in parents:
                # Parent comments that have been removed are still returned
                # when children exist and are authored by _nobody_. Such
                # should not be deleted remotely, but only marked internally.
                if comment["who"] != "_nobody_":
                    self.delete(comment["id"])
                del comments[comment["id"]]

        return comments

    def delete_from(self, request_id=None, project_name=None, package_name=None):
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
        self, user, request_id=None, project_name=None, package_name=None
    ):
        """Remove comments where @user is mentioned.

        This method is used to remove notifications when a request is
        removed or moved to another project.
        :param user: User name where the comment will be removed.
        :param request_id: Request where to remove comments.
        :param project_name: Project name where to remove comments.
        :param package_name: Package name where to remove comments.
        :return: Number of comments removed.
        """
        for comment in list(
            self.get_comments(request_id, project_name, package_name).values()
        ):
            if comment["who"] == user:
                self.delete(comment["id"])
