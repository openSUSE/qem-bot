[![ci](https://github.com/openSUSE/qem-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/openSUSE/qem-bot/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/openSUSE/qem-bot/branch/master/graph/badge.svg?token=LTQET0ZPBG)](https://codecov.io/gh/openSUSE/qem-bot)
# bot-ng
"bot-ng" or "qem-bot" is a tool for scheduling maintenance tests on openQA based
on [SMELT](https://tools.io.suse.de/smelt) incidents and Gitea PRs.

It is tightly coupled with
[qem-dashboard](https://github.com/openSUSE/qem-dashboard) where it reads and
updates information about incidents and related openQA tests.

## Usage:

    >>> bot-ng.py --help
    Usage: bot-ng [-h] [-c CONFIGS] [--dry] [-d] -t TOKEN [-i OPENQA_INSTANCE]
                  [-s SINGLEARCH] [-r RETRY]
                  {full-run,incidents-run,updates-run,smelt-sync,inc-approve,inc-sync-results,aggr-sync-results}
                  ...

    QEM-Dashboard, SMELT and openQA connector

    positional arguments:
      {full-run,incidents-run,updates-run,smelt-sync,inc-approve,inc-sync-results,aggr-sync-results}
        full-run            Full schedule for Maintenance Incidents in openqa
        incidents-run       Incidents only schedule for Maintenance Incidents in
                            openqa
        updates-run         updates only schedule for Maintenance Incidents in
                            openqa
        smelt-sync          Sync data from SMELT into QEM Dashboard
        gitea-sync          Sync data from Gitea into QEM Dashboard
        inc-approve         Approve incidents which passed tests
        inc-comment         Comment incidents in BuildService
        inc-sync-results    Sync results of openQA incidents jobs to Dashboard
        aggr-sync-results   Sync results of openQA aggregates jobs to Dashboard

    optional arguments:
      -h, --help            show this help message and exit
      -c CONFIGS, --configs CONFIGS
                            Directory or single file with openqabot configuration metadata
      --dry                 Dry run, do not post any data
      -d, --debug           Enable debug output
      -t TOKEN, --token TOKEN
                            Token for qem dashboard api
      -i OPENQA_INSTANCE, --openqa-instance OPENQA_INSTANCE
                            OpenQA instance to use Other instances than OSD do not
                            update dashboard database
      -s SINGLEARCH, --singlearch SINGLEARCH
                            Yaml config with list of singlearch packages for
                            incidents run
      -r RETRY, --retry RETRY
                            Number of retries

## Expected workflow

* For every incident in SMELT an entry should show up in qem-dashboard
  (`smelt-sync`)
* For every incident in qem-dashboard incident and aggregate tests are
  triggered (`incidents-run+updates-run`)
* Results from incident + aggregate tests show up on the dashboard
  (`inc-sync-results+aggr-sync-results`)
* If there is a non-zero amount of related openQA jobs *and* none of them
  failed then qem-bot approves in IBS (`inc-approve`)

### Deployment
This script is *not* a service that is running constantly at some host. So the
"deployment" is only done in form of regularly scheduled CI jobs. See
https://gitlab.suse.de/qa-maintenance/bot-ng/-/blob/master/Readme.md for the
SUSE-internal CI setup.

## Misc

**Token** is required but if isn't used https://openqa.suse.de or is invoked with
`--dry` argument any string is sufficient -> see [qem-dashboard](https://github.com/openSUSE/qem-dashboard)

## Commenting in IBS

Action `inc-comment` can be used to add comments to release requests inside IBS (like [qa-maintenance/openQABot](https://gitlab.suse.de/qa-maintenance/openQABot) did).

An example of such comment:

```
<!-- openqa state=failed revision_15-SP3_x86_64=1636983205 revision_15-SP3_ppc64le=1636982976 revision_15-SP3_s390x=1636982978 revision_15-SP3_aarch64=1636982975 revision_15.3_x86_64=0 -->


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

bot-ng outputs in info log messages the openqa-cli commands that can be called
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
* Run `black .` before committing changes to format code according to our
  standards. Preferably also run other tests as described in the subsequent
  section.
* As a SUSE colleague consider signing commits which we consider to use for
  automatic deployments within SUSE.

If this is too much hassle for you feel free to provide incomplete pull requests
for consideration or create an issue with a code change proposal.

### Local testing

Ensure you have the dependencies for development installed. The easiest
way to get them is via pip:

    pip install -r requirements-dev.txt

There are currently only limited automatic tests available. Run `make test`
or `pytest` to execute Python-based unit tests. Run e.g.
`pytest tests/test_amqp.py` to execute a single test.

Run `make checkstyle` to check coding style and `make lint` for linting.

Another simple way for at least syntax correctness checks is to just call
`./bot-ng.py --help` to show the help text if the source can be correctly
parsed. The next recommended way for testing is to call `bot-ng.py` with the
`--dry` command line parameter in different modes. This might need additional
data, e.g. "metadata" from https://gitlab.suse.de/qa-maintenance/metadata/ .
For example with cloning this metadata as well as specifying a fake token
value that is enough for testing:

```
git clone --depth 1 gitlab@gitlab.suse.de:qa-maintenance/metadata.git
./bot-ng.py --configs metadata -t 1234 --dry inc-approve
```

This should walk over the list of current incidents pending approval.

It is possible to run qem-bot inside container, please see
[docs/containers](https://github.com/openSUSE/qem-bot/tree/main/doc/containers.md).

#### Local integration testing with qem-dashboard and openQA
Checkout [qem-dashboard](https://github.com/openSUSE/qem-dashboard) and follow
the instructions from its README to setup up. Then all you need to do to start
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
./bot-ng.py -g "$GITEA_TOKEN" -t s3cret --fake-data -c etc/openqabot gitea-sync --allow-build-failures --consider-unrequested-prs
```

The `--fake-data` switch means that it will not actually query Gitea and just
use some fake data instead. You can leave it out to test the integration with
Gitea as well.

---

Then you can trigger some openQA tests specifying some metadata:

```
MAIN_OPENQA_DOMAIN=[::1]:9526 ./bot-ng.py -t s3cret -c etc/openqabot/slfo.yml -s etc/openqabot/slfo.yml -i 'http://[::1]:9526' incidents-run
```

The YAML document containing metadata can look like
[this](https://progress.opensuse.org/issues/180812#note-24). Of course this
needs according product definitions, test suites and a job group with job
templates on openQA for any jobs to be actually scheduled. Using scenario
definitions would also generally be possible but hasn't been tried yet.

---

Then you can sync back the result of the openQA tests to the dashboard:

```
MAIN_OPENQA_DOMAIN=[::1]:9526 ./bot-ng.py -t s3cret -c etc/openqabot/slfo.yml -s etc/openqabot/slfo.yml -i 'http://[::1]:9526' inc-sync-results
```

To fake test results you can use an SQL command like
`update jobs set state = 'done', result = 'softfailed' where state = 'scheduled';`
on your local openQA database.

If you want to re-try these steps from scratch you need to clean-up incident
settings from the qem-dashboard database with an SQL command like
`delete from incident_openqa_settings where id >= …;`.

---

You can also finally approve incidents/PRs based on the openQA test results,
e.g.:

```
MAIN_OPENQA_DOMAIN=[::1]:9526 ./bot-ng.py --dry -g "$GITEA_TOKEN_WRITE" -t s3cret -c etc/openqabot/slfo.yml -s etc/openqabot/slfo.yml -i 'http://[::1]:9526' inc-approve
```

If you want to approve incidents for real you have to leave out the `--dry` flag
of course. Then a token with write-permissions is required.

## License

This project is licensed under the MIT license, see LICENSE file for details.
Some exceptions apply and are marked accordingly.
