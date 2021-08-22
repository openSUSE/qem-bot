# bot-ng

tool for shedule maintenance jobs + sync SMELT/OpenQA to QEM-Dashboard

## Usage:

    >>> bot-ng.py --help
    
    Usage: bot-ng [-h] [-c CONFIGS] [--dry] [-d] -t TOKEN 
                  {full-run,incidents-run,updates-run,smelt-sync,inc-approve,inc-sync-results,aggr-sync-results}
                  ...
    
    QEM-Dashboard, SMELT and openQA connector
    
    positional arguments:
      {full-run,incidents-run,updates-run,smelt-sync,inc-approve,inc-sync-results,aggr-sync-results}
        full-run            Full shedule for Maintenance Incidents in openqa
        incidents-run       Incidents only shedule for Maintenance Incidents in
                            openqa
        updates-run         updates only shedule for Maintenance Incidents in
                            openqa
        smelt-sync          Sync data from SMELT into QEM Dashboard
        inc-approve         Aprove incidents which passed tests
        inc-sync-results    Sync results of openQA incidents jobs to Dashboard
        aggr-sync-results   Sync results of openQA aggregates jobs to Dashboard
    
    optional arguments:
      -h, --help            show this help message and exit
      -c CONFIGS, --configs CONFIGS
                            Directory with openqabot configuration metadata
      --dry                 Dry run, dont post any data
      -d, --debug           Enable debug output
      -t TOKEN, --token TOKEN
                            Token for qem dashboard api
    
