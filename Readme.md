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
    │ --dry                               Dry run, do not post any data            │
    │ --fake-data                         Use fake data, do not query data from    │
    │                                     real services                            │
    │ --dump-data                         Dump requested data for later use via    │
    │                                     --fake-data                              │
    │ --debug            -d               Enable debug output                      │
    │ --token            -t      TEXT     Token for qem dashboard api              │
    │ --gitea-token      -g      TEXT     Token for Gitea api                      │
    │ --openqa-instance  -i      TEXT     The openQA instance to use Other         │
    │                                     instances than OSD do not update         │
    │                                     dashboard database                       │
    │ --singlearch       -s      PATH     Yaml config with list of singlearch      │
    │                                     packages for submissions run             │
    │ --retry            -r      INTEGER  Number of retries                        │
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
  failed then qem-bot approves in IBS/OBS or Gitea (`sub-approve`)
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

## Commenting in IBS

Action `sub-comment` can be used to add comments to release requests inside IBS (like [qa-maintenance/openQABot](https://gitlab.suse.de/qa-maintenance/openQABot) did).

An example of such comment:

```
<!-- openqa state=failed revision_15-SP3_x86_64=1636983205
revision_15-SP3_ppc64le=1636982976 revision_15-SP3_s390x=1636982978
revision_15-SP3_aarch64=1636982975 revision_15.3_x86_64=0 -->


 __Group [Maintenance: Containers 15-SP3 Updates@Server-DVD-Updates](https://openqa.suse.de/tests/overview?version=15-SP3&groupid=369&flavor=Server-DVD-Updates&distri=sle&build=20211115-1)__
 (6 tests passed)


 __Group [Maintenance: JeOS 15-SP3 Updates@JeOS-for-kvm-and-xen-Updates](https://openqa.suse.de/tests/overview?version=15-SP3&groupid=375&flavor=JeOS-for-kvm-and-xen-Updates&distri=sle&build=20211115-1)__
 (30 tests passed)


 __Group [Maintenance: Public Cloud 15-SP3 Updates@GCE-Updates](https://openqa.suse.de/tests/overview?version=15-SP3&groupid=370&flavor=GCE-Updates&distri=sle&build=20211115-1)__
 (5 tests passed, 1 tests failed)

 - [sle-15-SP3-GCE-Updates-x86_64-Build20211115-1-publiccloud_containers@64bit](https://openqa.suse.de/tests/7676191) failed'

 __Group [Maintenance: SLE 15 SP3 Incidents@Desktop-DVD-Incidents](https://openqa.suse.de/tests/overview?version=15-SP3&groupid=367&flavor=Desktop-DVD-Incidents&distri=sle&build=%3A21811%3Aautoyast2)__
 (3 tests passed, 2 tests failed)

 - [sle-15-SP3-Desktop-DVD-Incidents-x86_64-Build:21811:autoyast2-qam-regression-piglit@64bit](https://openqa.suse.de/tests/7679142) is waiting'
 - [sle-15-SP3-Desktop-DVD-Incidents-x86_64-Build:21811:autoyast2-qam-regression-other@64bit](https://openqa.suse.de/tests/7679143) is waiting'


 __Group [Maintenance: SLE 15 SP3 Updates@Server-DVD-Updates](https://openqa.suse.de/tests/overview?version=15-SP3&groupid=366&flavor=Server-DVD-Updates&distri=sle&build=20211115-1)__
 (147 tests passed)
```

## Manual triggering of actions

### Manual execution of pre-defined actions

All pre-defined actions are executed based on gitlab CI definitions based on
pipeline schedules. If needed for special circumstances one can also manually
run any of the predefined schedules from
https://gitlab.suse.de/qa-maintenance/bot-ng/-/pipeline_schedules at any time
with a click of a button.
To manually customize the parameters
https://gitlab.suse.de/qa-maintenance/bot-ng/-/pipelines/new
can be used.

### Manual triggering of openQA jobs

qem-bot outputs in info log messages the openqa-cli commands that can be called
to manually replicate the openQA job triggering. For example log output
message might look like:

```
INFO: openqa-cli --host https://openqa.suse.de api -X post isos ARCH=s390x BASE_TEST_ISSUES=20937,21863 FLAVOR=Server-DVD-Updates BUILD=20211215-1
```

The same command can be called manually to re-schedule all tests for this
build or settings can be tweaked accordingly, e.g. a new build value could
be selected so that the command to call would look like this:

```
openqa-cli --host https://openqa.suse.de api -X post isos ARCH=s390x BASE_TEST_ISSUES=20937,21863 FLAVOR=Server-DVD-Updates BUILD=20211215-2
```

Apply caution to keep all the other parameters in place.

## Contribute

This project lives in https://github.com/openSUSE/qem-bot

Feel free to add issues in github or send pull requests.

### Rules for commits

* For git commit messages use the rules stated on
  [How to Write a Git Commit Message](http://chris.beams.io/posts/git-commit/)
  as a reference.
* Every commit MUST ensure full statement and branch coverage.
* Run `make tidy` before committing changes to format code according to our
  standards. Preferably also run other tests as described in the subsequent
  section.
* As a SUSE colleague consider signing commits which we consider to use for
  automatic deployments within SUSE.

If this is too much hassle for you feel free to provide incomplete pull requests
for consideration or create an issue with a code change proposal.

### Local testing

Ensure you have the dependencies for development installed. The easiest
way to get them is via uv:

    uv sync

For local development, you can use `uv` to create a virtual environment and
install dependencies:

    uv venv
    source .venv/bin/activate
    uv sync

There are several Makefile targets available for development. Run `make help`
to see a full list of available targets.

There are currently only limited automatic tests available. Run `make test`
or `pytest` to execute Python-based unit tests. Run e.g.
`pytest tests/test_amqp.py` to execute a single test.

Run `make test-with-coverage` to check for 100% statement and branch coverage.

Run `make checkstyle` to run all style and static analysis checks.

Run `check-maintainability` to check maintainability. This requires the tool
`radon`. You can also check individual files displaying the exact percentage via
e.g. `radon mi --show tests/test_loader_incrementconfig.py`. Note that this kind
of metric is not about specific bad patterns but rather counts constructs like
`if` statements. Check out the
[Radon documentation](https://radon.readthedocs.io/en/latest/intro.html) for
details. There is also
[documentation about the thresholds](https://radon.readthedocs.io/en/latest/commandline.html#the-mi-command)
for the grades.

Another simple way for at least syntax correctness checks is to just call
`python3 ./qem-bot.py --help` to show the help text if the source can be
correctly parsed. The next recommended way for testing is to call `qem-bot.py`
with the `--dry` command line parameter in different modes. This might need
additional data, e.g. "metadata" from
https://gitlab.suse.de/qa-maintenance/metadata/ .
For example with cloning this metadata as well as specifying a fake token
value that is enough for testing:

```
git clone --depth 1 gitlab@gitlab.suse.de:qa-maintenance/metadata.git
python3 ./qem-bot.py --configs metadata -t 1234 --dry sub-approve
```

This should walk over the list of current submissions pending approval.

It is possible to run qem-bot inside a container, please see
[docs/containers](https://github.com/openSUSE/qem-bot/tree/main/doc/containers.md).

#### Local integration testing with qem-dashboard and openQA
Check out [qem-dashboard](https://github.com/openSUSE/qem-dashboard) and follow
the instructions from its README to set up. Then all you need to do to start
the dashboard is:

```
mojo webpack script/dashboard
```

---

For setting up openQA you can follow its
[installation guide](https://open.qa/docs/#installing) or go all in and also
[create a development setup for openQA](https://open.qa/docs/#development-setup).

---

The first bot command you want to invoke is one of the `…-sync` commands, e.g.
the following one to sync Gitea PRs into the dashboard:

```
python3 ./qem-bot.py -g "$GITEA_TOKEN" -t s3cret --fake-data \
    -c etc/openqabot gitea-sync --allow-build-failures \
    --consider-unrequested-prs
```

The `--fake-data` switch means that it will not actually query Gitea and just
use some fake data instead. You can leave it out to test the integration with
Gitea as well.

---

Then you can trigger some openQA tests specifying some metadata:

```
MAIN_OPENQA_DOMAIN=[::1]:9526 python3 ./qem-bot.py -t s3cret -c etc/openqabot/slfo.yml -s etc/openqabot/slfo.yml -i 'http://[::1]:9526' submissions-run
```

The YAML document containing metadata can look like
[this](https://progress.opensuse.org/issues/180812#note-24). Of course this
needs according product definitions, test suites and a job group with job
templates on openQA for any jobs to be actually scheduled. Using scenario
definitions would also generally be possible but hasn't been tried yet.

---

Then you can sync back the result of the openQA tests to the dashboard:

```
MAIN_OPENQA_DOMAIN=[::1]:9526 python3 ./qem-bot.py -t s3cret -c etc/openqabot/slfo.yml -s etc/openqabot/slfo.yml -i 'http://[::1]:9526' sub-sync-results
```

To fake test results you can use an SQL command like
`update jobs set state = 'done', result = 'softfailed'
where state = 'scheduled';`
on your local openQA database.

If you want to re-try these steps from scratch you need to clean up incident
settings from the qem-dashboard database with an SQL command like
`delete from incident_openqa_settings where id >= …;`.

---

You can also finally approve submissions based on the openQA test results,
e.g.:

```
MAIN_OPENQA_DOMAIN=[::1]:9526 python3 ./qem-bot.py --dry -g "$GITEA_TOKEN_WRITE" -t s3cret -c etc/openqabot/slfo.yml -s etc/openqabot/slfo.yml -i 'http://[::1]:9526' sub-approve
```

If you want to approve submissions for real you have to leave out the `--dry`
flag of course. Then a token with write-permissions is required.

---

You can also test the increment approval, e.g.:

```
python3 ./qem-bot.py --debug --dry -t not-secret -i 'http://[::1]:9526' increment-approve --accepted --request-id 391430 --flavor Online-Increments --schedule --diff-project-suffix none
```

In production you should specify the config via `--config`, though. Check out
[the config documentation](doc/config.md) for details. It also explains what
this command does step by step.

The parameter `--request-id 391430` is useful to skip the expensive OBS query
for finding the most recent request. The parameter `--accepted` is useful if
there is currently no open request.

The parameter `--diff-project-suffix none` avoids the expensive computation of
the repo diff which you probably don't want/need unless you are testing that
specific aspect of the command.

This command doesn't use the dashboard which is therefore not required.

## License

This project is licensed under the MIT license, see LICENSE file for details.
Some exceptions apply and are marked accordingly.
