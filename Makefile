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

.PHONY: test-with-coverage
test-with-coverage:
	python3 -m pytest -v --cov=./openqabot --cov-report=xml --cov-report=term

# aggregate targets

.PHONY: checkstyle
checkstyle: ruff

.PHONY: test
test: only-test checkstyle
