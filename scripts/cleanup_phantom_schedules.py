#!/usr/bin/env python3
# Copyright SUSE LLC
# SPDX-License-Identifier: MIT
"""Script to identify and unblock active submissions stuck in a phantom schedule state."""

import json
import logging
import re
import subprocess  # noqa: S404
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Add project root to sys.path to allow imports from openqabot if needed
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")
log = logging.getLogger(__name__)

# Range of job IDs for schedule submissions dry-runs (the dry-run bug period):
FIRST_BAD_JOB = 6917520
FIXED_JOB = 6935277


def _get_settings(inc_number: int, inc_type: str) -> list[dict]:
    """Fetch settings for a single incident."""
    settings_url = f"https://dashboard.qam.suse.de/api/incident_settings/{inc_number}"
    if inc_type != "smelt":
        settings_url += f"?type={inc_type}"

    try:
        with urllib.request.urlopen(settings_url) as resp:  # noqa: S310
            data = resp.read().decode("utf-8")
            return json.loads(data)
    except (urllib.error.URLError, json.JSONDecodeError):
        return []


def _has_actual_jobs(setting_id: int) -> bool:
    """Check if any actual jobs exist for a setting."""
    jobs_url = f"https://dashboard.qam.suse.de/api/jobs/incident/{setting_id}"
    try:
        with urllib.request.urlopen(jobs_url) as resp:
            data = resp.read().decode("utf-8")
            jobs_list = json.loads(data)
            return isinstance(jobs_list, list) and len(jobs_list) > 0
    except (urllib.error.URLError, json.JSONDecodeError):
        return False


def _is_phantom_setting(setting: dict) -> bool:
    """Check if a single setting belongs to a bad dry-run job."""
    job_url = setting.get("settings", {}).get("__CI_JOB_URL", "")
    m = re.search(r"/jobs/(\d+)", job_url)
    if m:
        job_id = int(m.group(1))
        return FIRST_BAD_JOB <= job_id < FIXED_JOB
    return False


def check_incident(inc: dict) -> str | None:
    """Check if a single active incident is stuck in the phantom schedule state."""
    inc_number = inc.get("number")
    inc_type = inc.get("type", "smelt")

    if not inc_number:
        return None

    settings = _get_settings(inc_number, inc_type)
    if not settings:
        return None

    has_phantom = False
    has_any_jobs = False

    for setting in settings:
        if _is_phantom_setting(setting):
            has_phantom = True
        if _has_actual_jobs(setting.get("id", 0)):
            has_any_jobs = True

    if has_phantom and not has_any_jobs:
        return f"{inc_type}:{inc_number}"

    return None


def main() -> int:
    """Run the phantom schedule cleanup process."""
    url = "https://dashboard.qam.suse.de/api/incidents"
    log.info("Fetching active incidents from %s", url)
    try:
        with urllib.request.urlopen(url) as response:
            data = response.read().decode("utf-8")
            incidents = json.loads(data)
    except (urllib.error.URLError, json.JSONDecodeError):
        log.exception("Failed to fetch active incidents from QEM Dashboard")
        return 1

    log.info("Loaded %d active incidents from QEM Dashboard", len(incidents))
    log.info("Checking active incidents in parallel for phantom schedule states...")

    stuck_all = []
    # Check all active incidents concurrently
    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(check_incident, inc): inc for inc in incidents}
        for f in futures:
            res = f.result()
            if res:
                stuck_all.append(res)

    if not stuck_all:
        log.info("No stuck active submissions found in a phantom schedule state. All is good!")
        return 0

    log.warning("Found %d stuck active submissions in a phantom schedule state:", len(stuck_all))
    for sub in sorted(stuck_all):
        log.warning("  - %s", sub)

    log.info("Unblocking stuck submissions by triggering a targeted submissions-run...")
    for sub in sorted(stuck_all):
        log.info("Triggering submissions-run --ignore-onetime for %s", sub)
        try:
            subprocess.run(  # noqa: S603
                [sys.executable, "./qem-bot.py", "submissions-run", "--submission", sub, "--ignore-onetime"],
                check=True,
            )
            log.info("Successfully unblocked %s", sub)
        except subprocess.SubprocessError:
            log.exception("Failed to trigger unblock run for %s", sub)

    log.info("Phantom schedule cleanup completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
