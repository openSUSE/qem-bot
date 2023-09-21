# Configuration format of qem-bot

Configuration, in another way also called metadata of qem-bot, is held in yaml files with one file per "product". Additionally, there is one special config file called `singlearch.yml` which contains a list of packages that exist only on a single architecture.
Configuration usually spans over multiple files. The default location accepted from qem-bot is `/etc/openqabot/`. All configuration files must have `.yml` or `.yaml` extension.

```bash
/etc/openqabot ❯❯❯ tree
.
├── singlearch.yml
├── leap154.yml
├── sles15sp3.yml
├── micro53.yml
...
```

Example of `singlearch.yml`:

```yaml
- packageone
- packagetwo
- onlyppcle
```

If an incident has a package from this list, a job is automatically marked as without **aggregate**. That means the Incident can be approved without existing aggregate jobs.
Other yaml files contain the definition of **product** and data either or both **aggregate** and **incidents**


## Structure of a product definition

Contains unique identification of a **product**, common settings and `DISTRI` plus `VERSION` variables for openQA.

Example:

```yaml
product: leap155
settings:
  DISTRI: opensuse
  VERSION: '15.5'
  SOMETHING: 'something123'
  ELSE: 'ELSE123'
```

* `product` - mandatory and must be unique, no other config file can have the same product. 
* `settings` - mandatory mapping containing `key` : `value` which are used directly in job schedule. From this the pairs `DISTRI` and `VERSION` are mandatory.

## Aggregate part of the configuration

Used to schedule multiple Incidents in a product as one BUILD named **YYYYMMDD-{counter from 1}**. Jobs scheduled on this part of the config will have multiple vars `*_TEST_REPO` used to add Incident repositories. 

Example:

```yaml
 aggregate:
  FLAVOR: Shiny-New-Flavour
  archs:
    - aarch64
    - s390x
  test_issues:
    BASE_TEST_ISSUES: Basesystem:17-SP5
    OS_TEST_ISSUES: Product-Linux:17-SP5
    SERVERAPP_TEST_ISSUES: Module-Server-Applications:17-SP5
    DESKTOP_TEST_ISSUES: Module-Desktop-Applications:17-SP5
    SDK_TEST_ISSUES: Development-Tools:17-SP5
    PCM_TEST_ISSUES: Public-Cloud:17-SP5
  onetime: true
```

* `aggregate` - self-explanatory, mapping containing all needed settings for the aggregate schedule of a given *product*
* `FLAVOR` - flavor used by the schedule, can be only once per product, mandatory
* `archs` - list scheduled architectures, mandatory
* `test_issues` - mandatory, contains a mapping of `*_TEST_ISSUES`, which are used to decide which Incidents to be scheduled in aggregate jobs. Values are `PRODUCT-IDENTIFICATION:VERSION`. `PRODUCT-IDENTIFICATION` as defined in OBS/IBS. `VERSION` same as `PRODUCT-IDENTIFICATION`, could use different versions for different `*_TEST_ISSUES`.
  * `OS_TEST_ISSUES` variable is implicit, always used by *os-autoinst-distri-opensuse*, contains identification of the base product.
  * All others contain modules, addons, and extensions used in this aggregate. First part of the key name must be the same (uppercase, os-autoinst-distri-opensuse will convert it to lowercase) as an addon, extension or module identification in `SCC_ADDONS` variable defined in the job template inside the openQA instance.
* `onetime` - optional key, boolean. By default, qem-bot sets it to `False`. When set to `True`, it limits bot scheduling this aggregate to only once per day.

## Incidents part of the configuration

Used to schedule jobs per one Incident. Scheduled jobs will have BUILD **:INCIDENT_NR:shortest_package_name**. All needed links to scheduled incident repositories are in the `INCIDENT_REPO` variable.

Example:

```yaml
incidents:
  FLAVOR:
    Some-Incident-Flavor:
      archs:
        - x86_64
        - aarch64
      issues:
         BASE_TEST_ISSUES: Basesystem:17-SP5
         OS_TEST_ISSUES: Product-Linux:17-SP5
         SERVERAPP_TEST_ISSUES: Module-Server-Applications:17-SP5
         DESKTOP_TEST_ISSUES: Module-Desktop-Applications:17-SP5
         SDK_TEST_ISSUES: Development-Tools:17-SP5
         PCM_TEST_ISSUES: Public-Cloud:17-SP5
      required_issues:
         - PCM_TEST_ISSUES
         - BASE_TEST_ISSUES
      aggregate_job: false
      aggregate_check_true:
         - KEYONE
      aggregate_check_false:
         - KEYTWO
         - KEYTHREE
      override_priority: 100
      params_expand:
        FOO: foo
        BAR: bar
      packages:
        - pkgone
        - pkgtwo
      excluded_packages:
        - pkgthree
        - pkgfour
    Other-Incident-FLavor:
      ...
```

* `incidents` mapping contains all settings for an incident schedule of a product.
* `FLAVOR` mapping containing FLAVORs and all settings needed to schedule them. FLAVOR itself maps 1:1 to an openQA's FLAVOR
* `archs` - list of scheduled architectures, mandatory
* `issues` - mandatory, same rules as `test_issues` of aggregate
* `required_issues` - optional, contains a list of `issues` keys which must be part of the Incident to be scheduled. Without this key, any incident containing any target in `issues` will be scheduled in this FLAVOR.
* `aggregate_job` - optional, boolean value, by default is `true`. When set to `false` it indicates this FLAVOR doesn't need an aggregate job for approval.
* `aggregate_check_true` and `aggregate_check_false` - optional, list of keywords, used only with `aggregate_job: false`. Conditions for finely tune the need of the Aggregate jobs for approval. Keywords are keys of variables used by job.
* `override_priority` - optional, integer. Overrides the default priority of the job. (default = 50, with modifiers for `*Minimal`, EMU and staging Incidents)
* `packages` - optional, list of package names (or first part of pkg name). The incident must contain a package from this list to be scheduled into openQA.
* `excluded_packages` - optional, list of package names, opposite to `packages`. If the Incident contains a package in this list, it isn't scheduled.

All optional keys can be omitted. By default qem-bot schedules Incidents for any matching `issue`, for any package in Incident, with computed job priority and with `aggregate_job: true`.
