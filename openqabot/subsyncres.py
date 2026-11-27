# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Sync submission results."""

from argparse import Namespace
from concurrent import futures
from itertools import chain, starmap
from logging import getLogger

from . import config
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
        submissions = list(chain.from_iterable(starmap(get_submission_settings_data, self.active)))
        full = {}
        with futures.ThreadPoolExecutor(max_workers=config.settings.max_workers) as executor:
            future_result = {executor.submit(self.client.get_jobs, f): f for f in submissions}
            for future in futures.as_completed(future_result):
                full[future_result[future]] = future.result()

        total_jobs = sum(len(job_results) for job_results in full.values())
        log.info("Fetched %s total jobs from openQA.", total_jobs)

        results = [
            r
            for submission, job_results in full.items()
            for job in job_results
            if self.filter_jobs(job) and (r := self.normalize_data_safe(submission, job))
        ]
        outcome = self.post_results(results)
        if outcome.failed:
            log.error(
                "Submission results sync incomplete: %s of %s job results failed after %s attempts "
                "and will be retried on the next run",
                outcome.failed,
                len(results),
                outcome.attempted,
            )
            return 1

        log.info("Submission results sync completed: Synced %s job results to the dashboard", len(results))
        return 0
