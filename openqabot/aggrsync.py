# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Sync aggregate results."""

from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import chain
from logging import getLogger

from .loader.config import read_products
from .loader.qem import get_aggregate_settings_data
from .syncres import SyncRes

log = getLogger("bot.aggrsync")


class AggregateResultsSync(SyncRes):
    """Synchronization of aggregate results."""

    operation = "aggregate"

    def __init__(self, args: Namespace) -> None:
        """Initialize the AggregateResultsSync class."""
        super().__init__(args)
        self.product = read_products(args.configs)

    def __call__(self) -> int:
        """Run the synchronization process."""
        log.info("Synchronizing results for %s products...", len(self.product))
        update_setting = list(chain.from_iterable(get_aggregate_settings_data(product) for product in self.product))

        job_results = {}
        with ThreadPoolExecutor() as executor:
            future_j = {executor.submit(self.client.get_jobs, f): f for f in update_setting}
            for future in as_completed(future_j):
                job_results[future_j[future]] = future.result()

        total_jobs = sum(len(v) for v in job_results.values())
        log.info("Fetched %s total jobs from openQA.", total_jobs)

        results = [
            r
            for key, values in job_results.items()
            for v in values
            if self.filter_jobs(v) and (r := self.normalize_data_safe(key, v))
        ]

        for r in results:
            self.post_result(r)
        log.info("Aggregate results sync completed: Synced %s job results to the dashboard", len(results))

        return 0
