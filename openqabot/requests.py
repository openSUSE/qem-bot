# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
import requests as req
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry


class requests:
    def get(url, **kwargs):
        s = req.Session()
        assert_status_hook = (
            lambda response, *args, **kwargs: response.raise_for_status()
        )
        s.hooks["response"] = [assert_status_hook]
        # retry more often for unavailable other services, e.g. smelt, see https://progress.opensuse.org/issues/113087
        a = HTTPAdapter(max_retries=Retry(total=20, backoff_factor=5))
        s.mount("http://", a)
        s.mount("https://", a)
        return s.get(url, **kwargs)
