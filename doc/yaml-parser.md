# YAML parsing of product data

Background for [`openqabot/yaml12.py`](../openqabot/yaml12.py), prompted by the review
discussion `openSUSE/qem-bot#704 r4710289758`.

## Decision

Product data is parsed with the **YAML 1.2 core schema plus the merge-key schema**:
`openqabot/yaml12.py` layers a merge-key resolver and a `construct_mapping` override on
`yamlcore.CCoreLoader`, the same composition `OpenQA::YAML` makes on YAML::PP. libyaml
stays the parser, so the speed of the previous C loader is unchanged.

## 1. Merge keys are a YAML 1.1 type

`<<` is `tag:yaml.org,2002:merge`, specified in `https://yaml.org/type/merge.html` as a
YAML **1.1** type. The current spec, `https://yaml.org/spec/1.2.2/`, contains zero
occurrences of "merge", and there is no 1.3 (`https://yaml.org/spec/1.3/` → 404). A
conformant 1.2 loader therefore reads `<<` as an ordinary string key unless it re-enables
the merge schema, which every loader used around openQA does.

Measured on the same snippets as block sequence items; the one flow-context caveat is in
section 5:

| input | PyYAML 1.1 | yamlcore 1.2 core | ruamel 1.2 |
|---|---|---|---|
| `yes` / `on` | `True` | `'yes'` / `'on'` | `'yes'` / `'on'` |
| `10:20` | `620` | `'10:20'` | `'10:20'` |
| `010` / `0o10` | `8` / `'0o10'` | `10` / `8` | `10` / `8` |
| `1_0` | `10` | `'1_0'` | `10` |
| `2024-01-01` | `date` | `'2024-01-01'` | `date` |
| `!!binary` / `!!timestamp` | resolved | `ConstructorError` | resolved |
| duplicate keys | silently last-wins | `ConstructorError` | `DuplicateKeyError` |
| `<<` merge | merged | string key | merged |

So ruamel is 1.2 plus 1.1 compatibility types, yamlcore is strict core, and merge keys are
a schema on top of either. No productcompose document uses any of the 1.1-only constructs.

## 2. The openQA ecosystem enables merge keys

| artifacts | example | consumer | semantics |
|---|---|---|---|
| openQA job groups/templates | `opensuse-jobgroups/job_groups/*.yaml` | openQA server via `OpenQA::YAML` | YAML::PP `schema => ['+', 'Merge']` = 1.2 core **plus** merge |
| openQA salt pillars | `salt-pillars-openqa/openqa/workerconf.sls` | Salt renderer | `SaltYamlSafeLoader` (PyYAML-based) → 1.1 + merge |
| GitLab CI files | `ci/ci/ssh-deploy.yml` | GitLab (Ruby Psych) | merge supported |
| job-group tooling | `opensuse-jobgroups/tool.py` | Python | `yaml.safe_load` (1.1 + merge) |

`os-autoinst/openQA` `lib/OpenQA/YAML.pm` states it explicitly: *"`+ Merge` is mnemonic
for 'Use the default schema PLUS the Merge schema'; `+` stands for the default schema
(YAML 1.2 Core); Merge is enabling Merge Keys `<<`"*. YAML::PP's FAQ agrees: merge keys
"can be enabled optionally". A Python loader without merge keys would behave differently
from openQA's own YAML layer on the same class of files.

## 3. Loader comparison

Speed is the minimum of 3–5 runs on the 701561 B `default.productcompose` of
`SUSE:SLFO:1.3:PullRequest:9997:SLES`, fetched from `https://api.suse.de`.
Conformance is the yaml-test-suite result from `https://matrix.yaml.info/valid.html`
(308 valid cases, run 2024-06-09), whose column legend is `ok, json_ok, n/i, diff, json_diff,
n/a, error`; a document the suite marks `diff` parses but yields different data.

| implementation | schema | merge | speed | conformance | Tumbleweed RPM |
|---|---|---|---|---|---|
| PyYAML `CSafeLoader` (previous) | 1.1 | yes | 57 ms | 249 ok, 9 json-ok, 45 diff | `python313-PyYAML` |
| **yamlcore `CCoreLoader` + merge schema (adopted)** | 1.2 core | yes | **55 ms** | not listed | `python313-yamlcore` |
| ruamel.yaml + `ruamel.yaml.clib` | 1.2 | yes | 129 ms | 265 ok, 6 json-ok, 37 diff | `python313-ruamel.yaml{,.clib}` |
| ruamel.yaml pure | 1.2 | yes | 745 ms | as above | as above |
| libfyaml (PyPI binding) | 1.2 | 1.2 mode no, 1.1 mode broken | 13 ms | 308 ok | C lib only, no binding package |
| `yaml_rs` (Rust) | 1.2 | no | 6 ms | 251 ok, 28 json-ok, 29 diff | none |
| `pyyaml-rs` | 1.1 | n/a | n/a | n/a | none |

## 4. Real-data check

All 15 documents fetched from production OBS (4 SLFO PR, 11 openSUSE/ALP/Leap, 2.8 MB)
parse to identical Python data under PyYAML 1.1, yamlcore 1.2, ruamel 1.2, libfyaml and
yaml_rs: no `<<`, no anchors, no 1.1-ambiguous scalars, no duplicate keys. Through
`productcompose._parse_productcompose` the arch→package mapping is identical too, and two
`qem-bot --dry advanced gitea-sync` runs with `--debug` produce byte-identical logs with the
old and the new loader. The 1.1/1.2 gap was latent, not an active defect: this change is
spec alignment, and it hardens the reader for documents that do use those constructs.

## 5. Why not the alternatives

- **PyYAML 1.1** (previous state): the flags above; upstream's 1.2 support is
  `yaml/pyyaml#555`, open since 2021.
- **ruamel.yaml + clib**: 1.2 and merge keys with an existing dependency, but 2.3× slower
  than libyaml, resolves 1.1-only `!!timestamp` and `1_0`, and its C parser rejects a plain
  scalar with `:` in flow context (`v: [10:20]`). The fallback if the merge override is
  not wanted.
- **libfyaml**: best conformance and 4× faster, but merge keys are unavailable in 1.2 mode
  and fail to parse in 1.1 mode, and its Python binding is 1.0.0rc2 without a distro
  package. Worth re-checking once merge keys work and it is packaged.
- **`yaml_rs`**: fastest and 1.2-correct, but archived.
- **Strict 1.2 without merge** (bare yamlcore, yaml_rs, libfyaml): diverges from
  `OpenQA::YAML`.

## 6. How `<<` is resolved

`_flatten_merge_keys` resolves a merge before construction, at the node level, the way PyYAML's
`flatten_mapping` does: each source's own pairs are inlined ahead of the merging node's pairs,
deduped by constructed key, so the node's own keys win over any source and an earlier source wins
over a later one. yamlcore's duplicate-key check therefore still sees only the node's own keys. A
source that contributes no pair (`&b {}`, `<<: []`) leaves the own keys alone, a key repeated
within one source is reported at that source like any duplicate key, and only a repeat across
sources is resolved first-wins. A merge whose source is the node itself resolves to the own keys,
because the `<<` pairs are removed before the sources are visited.

```yaml
outer:
  base: &base {k: v, x: 1}
m:
  <<: *base
  n: 2
```

→ `{'outer': {'base': {'k': 'v', 'x': 1}}, 'm': {'k': 'v', 'x': 1, 'n': 2}}`

Constructing a source instead (`self.construct_object(source)`) returns the empty mapping the
source's state generator yielded first and schedules the filling for a later round of
`construct_document`, so a source that is not filled yet copies nothing and adds no error. That is
every merge whose anchor is nested deeper than the merging key or lives in an earlier sequence
item; flat siblings only work by luck of draining order. `deep=True` does not help either, because
`construct_object` returns `constructed_objects[node]` (`yaml/constructor.py`) before it reads the
flag.

## 7. What the tests pin

`tests/test_yaml12.py` covers the 1.2 core scalars above, single and sequence merges, own keys
overriding merged ones, a merge through a mapping that itself merges, both shapes whose anchor is
constructed after the merging key (`anchor_nested_deeper`, `merge_from_earlier_sequence_item`),
sources that contribute no pair (`empty_merge_anchor`, `empty_merge_sequence`), a source that is
the node itself (`self_merge`, `self_merge_own_mapping`, `self_merge_sequence`), and the rejection of
duplicate keys and of invalid merge values, including a duplicate inside a merge source
(`merge_source_duplicate`, `merge_sequence_item_duplicate`).
`test_get_productcompose_packages_per_arch_fixture` pins the checked-in
`productcompose-124-…yaml` fixture mapping, and
`test_get_productcompose_packages_per_arch_resolves_merge_keys` pins a merged packageset
end to end. A full production document is checked manually, as recorded in section 4.

## 8. Swapping the backend

`openqabot/yaml12.py` is the only place that knows the library, so a future switch to
whatever gains merge-key support is one module plus the same tests — that is what makes the
choice future-proof, rather than any single library.
