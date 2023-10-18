.PHONY: all
all:

.PHONY: only-test
only-test:
	python3 -m pytest

.PHONY: tidy
tidy:
	black ./

.PHONY: flake8
flake8:
	flake8 ./openqabot pc_helper_online.py --config=setup.cfg

.PHONY: test-with-coverage
test-with-coverage:
	python3 -m pytest -v --cov=./openqabot --cov-report=xml --cov-report=term

# aggregate targets

.PHONY: checkstyle
checkstyle: flake8

.PHONY: test
test: only-test checkstyle
