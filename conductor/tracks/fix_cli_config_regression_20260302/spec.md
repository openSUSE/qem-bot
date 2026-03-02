# Specification: Fix CLI configuration path regression for single files

## Problem Statement
A regression in `openqabot/args.py` replaced the existence check for the `-c` / `--configs` argument with a strict directory check (`is_dir()`). This prevents users from providing a single YAML file as a configuration source, which is a documented and previously supported feature.

## Requirements
1. Restore support for single YAML files for the `--configs` / `-c` argument.
2. Update the error message from `"%s is not a valid directory"` to `"%s does not exist"` (or equivalent).
3. Ensure all affected subcommands (e.g., `full-run`, `smelt-sync`, etc.) are updated.
4. Update existing tests and add new tests to verify both directory and single-file configurations.

## Proposed Solution
- Modify `openqabot/args.py` to use `exists()` instead of `is_dir()` for path validation.
- Standardize the error message across all affected commands.
- Update `tests/test_args.py` to align with the new logic.
