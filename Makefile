SOURCE_FILES ?= $(shell git ls-files "**.py")

.PHONY: all
all:

.PHONY: only-test
only-test:
	python3 -m pytest

.PHONY: ruff
ruff:
	ruff check
	ruff format --check

.PHONY: tidy
tidy:
	ruff format
	ruff check --fix

.PHONY: check-conventions
check-conventions:
	@if git grep -nE '^\s*@(unittest\.mock\.|mock\.)?patch' tests/; then \
		echo "Error: @patch decorator detected. Avoid to prevent argument ordering bugs."; \
		echo "   Fix: Use the 'mocker' fixture (pytest-mock) or a 'with patch():' context manager."; \
		exit 1; \
	fi

.PHONY: check-maintainability
check-maintainability:
	@echo "Checking maintainability (grade B or worse) …"
	@radon mi ${SOURCE_FILES} -n B | (! grep ".")

.PHONY: check-code-health
check-code-health:
	@echo "Checking code health…"
	@vulture ${SOURCE_FILES} --min-confidence 80

.PHONY: typecheck
typecheck:
	PYRIGHT_PYTHON_FORCE_VERSION=latest pyright --skipunannotated --warnings

.PHONY: only-test-with-coverage
only-test-with-coverage:
	python3 -m pytest -v --cov --cov-report=xml --cov-report=term-missing

# aggregate targets

.PHONY: checkstyle
checkstyle: ruff check-conventions check-maintainability check-code-health typecheck

.PHONY: test
test: only-test checkstyle

.PHONY: test-with-coverage
test-with-coverage: only-test-with-coverage checkstyle

.PHONY: test-all-commands-unstable
test-all-commands-unstable:
	for i in incidents-run updates-run smelt-sync gitea-sync inc-approve inc-comment inc-sync-results aggr-sync-results increment-approve repo-diff amqp full-run; do echo "### $$i" && timeout 30 python3 ./qem-bot.py -t 1234 -c metadata/qem-bot --singlearch metadata/qem-bot/singlearch.yml --dry --fake-data $$i ; done
