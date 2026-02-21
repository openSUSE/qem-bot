[![ci](https://github.com/openSUSE/qem-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/openSUSE/qem-bot/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/openSUSE/qem-bot/branch/master/graph/badge.svg?token=LTQET0ZPBG)](https://codecov.io/gh/openSUSE/qem-bot)
# qem-bot
"qem-bot" is a tool for scheduling maintenance tests on openQA based on
various submission types:
* **SMELT incidents:** Maintenance incidents tracked in [SMELT](https://tools.io.suse.de/smelt).
* **Gitea PRs:** Pull Requests on Gitea (e.g. for [SLFO](https://src.suse.de/products/SLFO)).
* **Aggregates:** Testing of multiple maintenance incidents together in a single
  product repository.
* **Product Increments:** Approval of new product increments in OBS based on
  openQA results.

It is tightly coupled with
[qem-dashboard](https://github.com/openSUSE/qem-dashboard) where it reads and
updates information about submissions and related openQA tests.

## Usage:

<!-- usage_start -->

    >>> qem-bot.py --help

    Usage: qem-bot.py [OPTIONS] COMMAND [ARGS]...

    QEM-Dashboard, SMELT, Gitea and openQA connector

    ╭─ Options ────────────────────────────────────────────────────────────────────╮
    │ --configs          -c      PATH     Directory or single file with openqabot  │
    │                                     configuration metadata                   │
    │                                     [default: /etc/openqabot]                │
    │ --dry                               Dry run, do not post any data            │
    │ --fake-data                         Use fake data, do not query data from    │
    │                                     real services                            │
    │ --dump-data                         Dump requested data for later use via    │
    │                                     --fake-data                              │
    │ --debug            -d               Enable debug output                      │
    │ --token            -t      TEXT     Token for qem dashboard api              │
    │                                     [env var: QEM_BOT_TOKEN]                 │
    │ --gitea-token      -g      TEXT     Token for Gitea api                      │
    │ --openqa-instance  -i      TEXT     The openQA instance to use Other         │
    │                                     instances than OSD do not update         │
    │                                     dashboard database                       │
    │                                     [default: https://openqa.suse.de]        │
    │ --singlearch       -s      PATH     Yaml config with list of singlearch      │
    │                                     packages for submissions run             │
    │                                     [default: /etc/openqabot/singlearch.yml] │
    │ --retry            -r      INTEGER  Number of retries [default: 2]           │
    │ --help                              Show this message and exit.              │
    ╰──────────────────────────────────────────────────────────────────────────────╯
    ╭─ Commands ───────────────────────────────────────────────────────────────────╮
    │ full-run            Full schedule for Maintenance Submissions in openQA.     │
    │ submissions-run     Submissions only schedule for Maintenance Submissions in │
    │                     openQA.                                                  │
    │ updates-run         Aggregates only schedule for Maintenance Submissions in  │
    │                     openQA.                                                  │
    │ smelt-sync          Sync data from SMELT into QEM Dashboard.                 │
    │ gitea-sync          Sync data from Gitea into QEM Dashboard.                 │
    │ sub-approve         Approve submissions which passed tests.                  │
    │ sub-comment         Comment submissions in BuildService.                     │
    │ sub-sync-results    Sync results of openQA submission jobs to Dashboard.     │
    │ aggr-sync-results   Sync results of openQA aggregate jobs to Dashboard.      │
    │ increment-approve   Approve the most recent product increment for an OBS     │
    │                     project if tests passed.                                 │
    │ repo-diff           Computes the diff between two repositories.              │
    │ amqp                AMQP listener daemon.                                    │
    ╰──────────────────────────────────────────────────────────────────────────────╯


<!-- usage_end -->

## Configuration

The bot is configured primarily via YAML configuration files (see `-c` option).
You can also configure global settings using environment variables. See
[doc/config.md](doc/config.md#global-configuration-environment-variables) for
details.

## Expected workflow

* For every incident in SMELT or PR in Gitea an entry should show up in
  qem-dashboard (`smelt-sync`, `gitea-sync`)
* For every submission in qem-dashboard, submission and aggregate tests are
  triggered (`submissions-run`, `updates-run`)
* Results from submission + aggregate tests show up on the dashboard
  (`sub-sync-results`, `aggr-sync-results`)
* If there is a non-zero amount of related openQA jobs *and* none of them
  failed then qem-bot approves in OBS or Gitea (`sub-approve`)
* For product increments, qem-bot can also trigger tests and approve them
  (`increment-approve`)

### Deployment
This script is *not* a service that is running constantly at some host. So the
"deployment" is only done in form of regularly scheduled CI jobs. See
https://gitlab.suse.de/qa-maintenance/bot-ng/-/blob/master/Readme.md for the
SUSE-internal CI setup.

## Misc

**Token** is required, but if it isn't used https://openqa.suse.de or is invoked with
`--dry` argument any string is sufficient. See [qem-dashboard](https://github.com/openSUSE/qem-dashboard)

## Commenting in OBS

See [doc/usage.md](doc/usage.md#commenting-in-obs) for details.

## Manual triggering of actions

See [doc/development.md](doc/development.md#manual-triggering-of-actions) for
details.

## Contribute

See [doc/development.md](doc/development.md#contribute) for details.

## License

This project is licensed under the MIT license, see LICENSE file for details.
Some exceptions apply and are marked accordingly.
