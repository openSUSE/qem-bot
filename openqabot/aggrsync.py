# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import chain
from logging import getLogger

from .loader.config import read_products
from .loader.qem import get_aggregate_settings_data
from .syncres import SyncRes

log = getLogger("bot.aggrsync")


class AggregateResultsSync(SyncRes):
    operation = "aggregate"

    def __init__(self, args: Namespace) -> None:
        super().__init__(args)
        self.product = read_products(args.configs)

    def __call__(self) -> int:
        update_setting = list(
            chain.from_iterable(get_aggregate_settings_data(self.token, product) for product in self.product)
        )

        job_results = {}
        with ThreadPoolExecutor() as executor:
            future_j = {executor.submit(self.client.get_jobs, f): f for f in update_setting}
            for future in as_completed(future_j):
                job_results[future_j[future]] = future.result()

        results = [
            r
            for key, values in job_results.items()
            for v in values
            if self.filter_jobs(v) and (r := self._normalize_data(key, v))
        ]

        for r in results:
            self.post_result(r)

        log.info("Aggregate results sync completed")

        return 0
