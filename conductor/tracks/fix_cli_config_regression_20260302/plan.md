# Implementation Plan: Fix CLI configuration path regression for single files

## Phase 1: Research & Reproduction
- [ ] Task: Reproduce the configuration regression
    - [ ] Run: `uv run -p 3.11 qem-bot.py -d --token 'LAPIMPA' -i http://openqaworker15.qe.prg2.suse.org -c tests/fixtures/config/01_single.yml --dry incidents-run --ignore-onetime`
    - [ ] Verify it fails with "is not a valid directory" error.
- [ ] Task: Prepare tests for the fix in `tests/test_args.py`
    - [ ] Update `test_configs_not_dir_all_commands` to verify that a non-existent path still fails.
    - [ ] Add a new test case to verify that both directories and single YAML files are accepted as valid configuration sources for `incidents-run` and other commands.
    - [ ] Run tests and confirm that the single-file case fails before the fix.
- [ ] Task: Conductor - User Manual Verification 'Phase 1' (Protocol in workflow.md)

## Phase 2: Implementation (Green Phase)
- [ ] Task: Minimal fix: Remove redundant path validation in `openqabot/args.py`
    - [ ] Delete the `if not args.configs.is_dir(): ...` blocks from the subcommands.
- [ ] Task: Verify the fix with tests
    - [ ] Run `uv run make test` and ensure tests pass for both directory and single-file configuration sources.
- [ ] Task: Conductor - User Manual Verification 'Phase 2' (Protocol in workflow.md)

## Phase 3: Final Validation & Cleanup
- [ ] Task: Final verification with the reproduction command
    - [ ] Run the reproduction command again and confirm success.
- [ ] Task: Final quality checks
    - [ ] Run `uv run make tidy checkstyle typecheck-ty test-with-coverage`.
    - [ ] Ensure 100% coverage is maintained.
- [ ] Task: Conductor - User Manual Verification 'Phase 3' (Protocol in workflow.md)
