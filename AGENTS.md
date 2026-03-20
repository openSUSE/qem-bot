# qem-bot Agent Guidelines

Python CLI tool for scheduling maintenance tests on openQA. Uses: Python, osc,
openqa-client, pika, zstandard, requests, ruamel.yaml, jsonschema, lxml, ty,
ruff.

## Build & Test Commands

- `make tidy`: Format code with ruff.
- `make checkstyle`: Run full linting (ruff + radon + vulture).
- `make typecheck-ty`: Type checking.
- `make test`: Run all tests with full coverage

## Coverage Verification

- Always verify 100% statement AND branch coverage for all files using `make
  test`.
- Do NOT just look at the "passed" test count. You MUST check the exit code of
  `make test`. If it exits with an error (e.g. `Error 2` or `Coverage failure`),
  you must fix the coverage before committing.
- If an `elif` or `else` branch is logically unreachable (e.g. due to prior
  filtering), refactor the code to eliminate the unreachable branch to satisfy
  the coverage tool.

## Maintainability Verification

- Maintain Grade A (Radon MI >= 20) for all modified files.
- DO NOT use redundant comments or filler docstrings to artificially inflate
  MI scores.
- Achieve maintainability through genuine simplification: reduce complexity,
  nesting, and operands.
- Prefer private functions (`_` prefix) for internal helpers to bypass `ruff`
  docstring requirements (`D103`) instead of adding low-value documentation.

## Test Guidelines

- Prefer `@pytest.mark.parametrize` over individual single-assertion test
  functions for data-driven coverage. Use tuple form for argument names:
  `("arg1", "arg2")` not `"arg1,arg2"` (ruff PT006).
- Before creating a new test file, search existing tests for indirect coverage
  of the same code paths (e.g. integration tests that already exercise the
  function). Only add direct unit tests for logic not covered elsewhere.
- When adding tests for refactored code (e.g. enum replacements), verify the
  tests assert the *new* abstraction (e.g. `get_channel_type()`), not just
  re-test what integration tests already cover.
- Prefer adding test coverage in existing test files. Only when a completely
  new feature is implemented new test files should be considered.

## Plan Execution

- When an execution plan file exists in `tasks/`, read it fully before
  starting implementation. Follow the steps in order.
- When the user amends a plan, re-read it to identify what changed rather
  than re-deriving from scratch.

## Commit guidelines

- For any non-trivial changes, especially "fix" or "feat" commits mention
  motivation, design choices and user benefits in the git commit message
  body

## Architecture invariants

- Every `envvar=` name declared on a `typer.Option` in `args.py` MUST also
  appear as an `alias=` on a `Field` in `config.py`'s `Settings` class. When
  adding a new CLI flag with an env var, update both files. Enforced by
  `test_cli_envvars_covered_by_settings` in `tests/test_config.py`.

## Constraints

- `tasks/`: Read/write for planning. Never run git operations on this
  directory.
- Never run git clean or any command that deletes unversioned files. Ask for
  confirmation.
- Commit message format: 50/80 rule, 80-char limit, wrap in single quotes.
- **Style Exclusions**: NEVER suppress linter, type-checker, or coverage
  errors just to bypass them; you MUST refactor instead. Exclusions are ONLY
  permitted when dictated by external library interfaces (e.g., `# noqa:
  ANN401` for `Any` types). Such unavoidable exclusions MUST target the
  specific rule and include an explanatory comment.
