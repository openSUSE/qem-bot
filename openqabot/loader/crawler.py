# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Grep content of web page and filter it by provided regex."""

from __future__ import annotations

import logging
import re

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException
from urllib3.util.retry import Retry

from openqabot.config import settings

logger = logging.getLogger("bot.crawler")


class Crawler:
    """Class responsible for parsing IBS pages to find image/rpm names.

    verify (bool): Controls whether get responses will tolerate certificate errors
    """

    def __init__(self, *, verify: bool) -> None:
        """Initialize Crawler.

        Args:
            verify (bool): Controls whether get responses will tolerate certificate errors

        """
        self.verify: bool = verify
        retry_strategy = Retry(
            total=5,
            status_forcelist=frozenset([401, 403, 404, 413, 429, 503]),
            backoff_factor=1,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.retry_session = requests.Session()
        self.retry_session.mount("https://", adapter)
        self.retry_session.mount("http://", adapter)

    def get_regex_match_from_url(self, url: str, regex: str) -> re.Match[str] | None:
        """Get URL content and return back re.Match from content based on input regex or None when nothing was found.

        Args:
            url (str): target URL which will be parsed
            regex (str): Regex which will be used to create re.Match object

        Returns:
            Match[str] | None: Object containing matched results
            if nothing has been found None is returned

        """
        packages = self.crawl(url)
        if len(packages) < 1:
            logger.warning("For %s 0 items found", url)
            return None
        one_item_list = [p for p in packages if re.search(regex, p)]
        if len(one_item_list) > 1:
            logger.warning(
                "For %s we found more than one match for %s. \n %s",
                url,
                regex,
                one_item_list,
            )
        if not one_item_list:
            logger.warning("Nothing match %s in %s", regex, packages)
            return None
        return re.search(regex, one_item_list[0])

    def crawl(self, url: str) -> list[str]:
        """Fetch the given url and returns all href links in it."""
        url += "/?jsontable"
        try:
            resp = self.retry_session.get(url, timeout=settings.url_timeout, verify=self.verify)
            resp.raise_for_status()
        except (ConnectionError, RequestException) as ex:
            logger.warning(ex)
            return []

        try:
            data = resp.json()["data"]
        except requests.exceptions.JSONDecodeError as ex:
            logger.warning("During processing json from %s exception occured: %s", url, ex)
            return []

        return [file["name"] for file in data if not file["name"].endswith("/")]
