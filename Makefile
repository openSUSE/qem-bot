.PHONY: all
all:

.PHONY: only-test
only-test:
	python3 -m pytest

.PHONY: checkstyle
checkstyle:
	black --check ./

.PHONY: tidy
tidy:
	black ./

.PHONY: test-with-coverage
test-with-coverage:
	python3 -m pytest -v --cov=./openqabot --cov-report=xml --cov-report=term

.PHONY: test
test: only-test checkstyle
