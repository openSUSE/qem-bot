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
	ruff check --fix
	ruff format

.PHONY: typecheck
typecheck:
	PYRIGHT_PYTHON_FORCE_VERSION=latest pyright --skipunannotated

.PHONY: only-test-with-coverage
only-test-with-coverage:
	python3 -m pytest -v --cov --cov-report=xml --cov-report=term-missing

# aggregate targets

.PHONY: checkstyle
checkstyle: ruff typecheck

.PHONY: test
test: only-test checkstyle

.PHONY: test-with-coverage
test-with-coverage: only-test-with-coverage checkstyle

.PHONY: test-all-commands-unstable
test-all-commands-unstable:
	for i in incidents-run updates-run smelt-sync gitea-sync inc-approve inc-comment inc-sync-results aggr-sync-results increment-approve repo-diff amqp full-run; do echo "### $$i" && timeout 30 python3 ./qem-bot.py -t 1234 -c metadata/bot-ng --singlearch metadata/bot-ng/singlearch.yml --dry --fake-data $$i ; done
