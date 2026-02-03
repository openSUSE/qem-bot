# Configuration format of qem-bot

Configuration, also known as metadata of qem-bot, is held in yaml files with one file per "product". Additionally, there is one special config file called `singlearch.yml` which contains a list of packages that exist only on a single architecture.
Configuration usually spans over multiple files. The default location accepted by qem-bot is `/etc/openqabot/`. All configuration files must have `.yml` or `.yaml` extension.

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

If an incident has a package from this list, a job is automatically marked as not requiring **aggregate**. That means the Incident can be approved without existing aggregate jobs.
Other YAML files contain the definition of **product** and data for either or both **aggregate** and **submissions**


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
* `product_repo` - optional to use a specific product repo (e.g. `SLES-SAP` or `SLES-HA`) instead of the default derived from the PR (usually `SLES`)
* `product_version` - optional to override the product version (to use e.g. `16.0` instead of `15.99`)
* `settings` - mandatory mapping containing `key` : `value` which are used directly in job scheduling. Among these, the pairs `DISTRI` and `VERSION` are mandatory.

## Aggregate part of the configuration

Used to schedule multiple submissions in a product as one BUILD named **YYYYMMDD-{counter from 1}**. Jobs scheduled on this part of the config will have multiple vars `*_TEST_REPO` used to add Incident repositories.

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
* `archs` - list of scheduled architectures, mandatory
* `test_issues` - mandatory, contains a mapping of `*_TEST_ISSUES`, which are used to decide which submissions to be scheduled in aggregate jobs. Values are `PRODUCT-IDENTIFICATION:VERSION`. `PRODUCT-IDENTIFICATION` as defined in OBS/IBS. `VERSION` same as `PRODUCT-IDENTIFICATION`, could use different versions for different `*_TEST_ISSUES`.
  * `OS_TEST_ISSUES` variable is implicit, always used by *os-autoinst-distri-opensuse*, contains identification of the base product.
  * All others contain modules, addons, and extensions used in this aggregate. First part of the key name must be the same (uppercase, os-autoinst-distri-opensuse will convert it to lowercase) as an addon, extension or module identification in `SCC_ADDONS` variable defined in the job template inside the openQA instance.
* `onetime` - optional key, boolean. By default, qem-bot sets it to `False`. When set to `True`, it limits the bot from scheduling this aggregate to only once per day.

## Incidents part of the configuration

Used to schedule jobs per incident. Scheduled jobs will have the BUILD **:INCIDENT_NR:shortest_package_name**. All needed links to the scheduled incident repositories are in the `INCIDENT_REPO` variable.

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
    Other-Incident-Flavor:
      ...
```

* `incidents` mapping contains all settings for an incident schedule of a product.
* `FLAVOR` mapping containing FLAVORs and all settings needed to schedule them. FLAVOR itself maps 1:1 to an openQA FLAVOR
* `archs` - list of scheduled architectures, mandatory
* `issues` - mandatory, same rules as `test_issues` of aggregate
* `required_issues` - optional, contains a list of `issues` keys which must be part of the Incident to be scheduled. Without this key, any incident containing any target in `issues` will be scheduled in this FLAVOR.
* `aggregate_job` - optional, boolean value, by default is `true`. When set to `false` it indicates this FLAVOR doesn't need an aggregate job for approval.
* `aggregate_check_true` and `aggregate_check_false` - optional, list of keywords, used only with `aggregate_job: false`. Conditions to finely tune the need for Aggregate jobs for approval. Keywords are keys of variables used by job.
* `override_priority` - optional, integer. Overrides the default priority of the job. (default = 50, with modifiers for `*Minimal`, EMU and staging Incidents)
* `packages` - optional, list of package names (or first part of pkg name). The incident must contain a package from this list to be scheduled into openQA.
* `excluded_packages` - optional, list of package names, opposite of `packages`. If the Incident contains a package in this list, it isn't scheduled.
* `params_expand` - flavor specific settings. Merged with `settings` dictionary. `params_expand` values take precedence over `settings`. `DISTRI` and `VERSION` cannot be configured with `params_expand`.

All optional keys can be omitted. By default qem-bot schedules Incidents for any matching `issue`, for any package in Incident, with computed job priority and with `aggregate_job: true`.

## Structure of product definitions for product increments
The `increment-approve` command uses a different configuration format than
described above. The `increment-approve` can be run with its configuration
specified in the form of CLI arguments, see `qem-bot increment-approve -h` for
details. Alternatively, a config file (or directory) can be specified via
`qem-bot increment-approve --increment-config /path/to/config.yaml`. This config
file can contain one or more increment definitions, e.g.:

```
product_increments:
- distri: opensuse
  project_base: openSUSE:Factory
  build_project_suffix: ToTest
  diff_project_suffix: PUBLISH/product
  build_regex: '…'
  build_listing_sub_path: product
  product_regex: '^openSUSE-.*'
  settings:
    FOO: bar
  archs:
  - aarch64
  - x86_64
  packages:
  - foo
  - bar
  additional_builds:
  - build_suffix: kernel-livepatch
    regex: 'kernel-livepatch-(?P<kernel_version>[^\-]*?-[^\-]*?)-(?P<kind>rt)'
    settings:
      FLAVOR: Base-RT-Updates
      KGRAFT: '1'
  - build_suffix: …
    regex: …
    settings:
      …
- distri: sle
  …
```

Note that this example just contains dummy values. As you can see you can
specify multiple increment definitions, each with their own project on OBS to
monitor for new increment requests. The fields `archs` and `packages` allow
filtering similar to what is possible for incidents.

`qem-bot` will go through all listed product increments. This is the sequence for
the example configuration above:

1. The OBS project `openSUSE:Factory:ToTest` is checked for open increment
   requests and only continue with the next steps if there is one.
2. The `product` subdirectory (as specified via `build_listing_sub_path`) of the
   download repository is checked for files matching `build_regex` to determine
   the available `FLAVOR` and `ARCH` values and the `BUILD` number.
    * The `DISTRI` variable is taken as-is from the config, e.g. here `DISTRI`
      will always be `opensuse` or `sle`.
    * The product name is also deduced via `build_regex` and then matched
      against `product_regex`. The increment definition is only considered when
      the `product_regex` matches.
3. A diff between the download repository under `openSUSE:Factory:PUBLISH/product`
   and `openSUSE:Factory:ToTest/product` is computed. If this is not wanted
   `diff_project_suffix` can be set to `none` to skip this step.
    * The regexes specified under `additional_builds` are matched against
      packages which have changed in the product increment. For each match, an
      additional scheduled product with the specified `build_suffix` and
      `settings`. For instance, here an additional scheduled product with
      settings like `BUILD=1234-kernel-livepatch` and `FLAVOR=Base-RT-Updates`
      would be created if a package like `kernel-livepatch-6_12_0-160000_5-rt`
      is added/changed by the product increment.
4. openQA is checked for a scheduled product matching the settings determined in
   the previous step.
    * If there is no scheduled product `qem-bot` won't approve the increment
      request. If `--schedule` is specified a new scheduled product will be
      created.
    * If there is a scheduled product `qem-bot` will determine whether all jobs
      look good and accept the increment request.
5. `qem-bot` will then go back to step 1 but this time check whatever OBS
   project has been specified for `sle`.

## Global Configuration (Environment Variables)

In addition to the YAML configuration files, `qem-bot` can be configured via
environment variables. These are useful for setting up connections to external
services and tweaking global behavior. For the current default values, please
refer to [openqabot/config.py](../openqabot/config.py).

| Variable | Description |
| :--- | :--- |
| `QEM_DASHBOARD_URL` | URL of the QEM Dashboard |
| `SMELT_URL` | URL of the SMELT instance |
| `GITEA_URL` | URL of the Gitea instance |
| `OBS_URL` | URL of the Open Build Service API |
| `AMQP_URL` | URL of the AMQP server |
| `MAIN_OPENQA_DOMAIN` | Domain of the main openQA instance (used for dashboard sync logic) |
| `QEM_BOT_DEPRIORITIZE_LIMIT` | Threshold for job group size to trigger priority reduction |
| `QEM_BOT_PRIORITY_SCALE` | Scaling factor for job priority calculation |
| `GIT_REVIEW_BOT` | Username of the bot account for code reviews |
