# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from concurrent import futures
from itertools import chain
from logging import getLogger

from .loader.qem import get_active_incidents, get_incident_settings_data
from .syncres import SyncRes

log = getLogger("bot.incsyncres")


class IncResultsSync(SyncRes):
    operation = "incident"

    def __init__(self, args: Namespace) -> None:
        super().__init__(args)
        self.active = get_active_incidents(self.token)

    def __call__(self) -> int:
        incidents = list(chain.from_iterable(get_incident_settings_data(self.token, inc) for inc in self.active))

        full = {}

        with futures.ThreadPoolExecutor() as executor:
            future_result = {executor.submit(self.client.get_jobs, f): f for f in incidents}
            for future in futures.as_completed(future_result):
                full[future_result[future]] = future.result()

        results = [
            r
            for key, value in full.items()
            for v in value
            if self.filter_jobs(v) and (r := self._normalize_data(key, v))
        ]

        for r in results:
            self.post_result(r)

        log.info("Incident results sync completed")

        return 0
