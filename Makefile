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

.PHONY: pylint
pylint:
	pylint ./openqabot pc_helper_online.py --rcfile=pylintrc

.PHONY: flake8
flake8:
	flake8 ./openqabot pc_helper_online.py --config=setup.cfg

.PHONY: lint
lint: pylint flake8

.PHONY: test-with-coverage
test-with-coverage:
	python3 -m pytest -v --cov=./openqabot --cov-report=xml --cov-report=term

.PHONY: test
test: only-test checkstyle lint
