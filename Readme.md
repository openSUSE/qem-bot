# bot-ng

tool for schedule maintenance jobs + sync SMELT/OpenQA to QEM-Dashboard

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
        inc-approve         Aprove incidents which passed tests
        inc-sync-results    Sync results of openQA incidents jobs to Dashboard
        aggr-sync-results   Sync results of openQA aggregates jobs to Dashboard
    
    optional arguments:
      -h, --help            show this help message and exit
      -c CONFIGS, --configs CONFIGS
                            Directory with openqabot configuration metadata
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

## Misc

**Token** is required but if isn't used https://openqa.suse.de or is invoked with
`--dry` argument any string is sufficient -> see [qem-dashboard](https://gitlab.suse.de/opensuse/qem-dashboard/-/issues/15)

