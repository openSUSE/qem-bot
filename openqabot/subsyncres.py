# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Sync submission results."""

from argparse import Namespace
from concurrent import futures
from itertools import chain
from logging import getLogger

from .loader.qem import get_active_submissions, get_submission_settings_data
from .syncres import SyncRes

log = getLogger("bot.subsyncres")


class SubResultsSync(SyncRes):
    """Synchronization of submission results."""

    operation = "submission"

    def __init__(self, args: Namespace) -> None:
        """Initialize the SubResultsSync class."""
        super().__init__(args)
        self.active = get_active_submissions()

    def __call__(self) -> int:
        """Run the synchronization process."""
        log.info("Synchronizing results for %s active submissions...", len(self.active))
        submissions = list(chain.from_iterable(get_submission_settings_data(sub) for sub in self.active))
        full = {}
        with futures.ThreadPoolExecutor() as executor:
            future_result = {executor.submit(self.client.get_jobs, f): f for f in submissions}
            for future in futures.as_completed(future_result):
                full[future_result[future]] = future.result()

        total_jobs = sum(len(v) for v in full.values())
        log.info("Fetched %s total jobs from openQA.", total_jobs)

        results = [
            r
            for key, value in full.items()
            for v in value
            if self.filter_jobs(v) and (r := self.normalize_data_safe(key, v))
        ]
        for r in results:
            self.post_result(r)
        log.info("Submission results sync completed: Synced %s job results to the dashboard", len(results))
        return 0
