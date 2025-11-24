UV := uv run

.PHONY: all
all:

.PHONY: sync
sync:
	uv sync --extra dev

.PHONY: only-test
only-test:
	$(UV) pytest

.PHONY: ruff
ruff:
	$(UV) ruff check
	$(UV) ruff format --check

.PHONY: tidy
tidy:
	$(UV) ruff check --fix
	$(UV) ruff format

.PHONY: test-with-coverage
test-with-coverage:
	$(UV) pytest -v --cov --cov-branch --cov-fail-under=72 --cov-report=xml --cov-report=term-missing

# aggregate targets

.PHONY: checkstyle
checkstyle: ruff

.PHONY: test
test: only-test checkstyle

.PHONY: test-all-commands-unstable
test-all-commands-unstable:
	for i in incidents-run updates-run smelt-sync gitea-sync inc-approve inc-comment inc-sync-results aggr-sync-results increment-approve repo-diff amqp full-run; do echo "### $$i" && timeout 30 ./qem-bot.py -t 1234 -c metadata/bot-ng --singlearch metadata/bot-ng/singlearch.yml --dry --fake-data $$i ; done
