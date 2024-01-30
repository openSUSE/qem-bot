.PHONY: all
all:

.PHONY: only-test
only-test:
	python3 -m pytest

.PHONY: black
black:
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
	echo $$?

.PHONY: test-with-coverage
test-with-coverage:
	python3 -m pytest -v --cov=./openqabot --cov-report=xml --cov-report=term

# aggregate targets

.PHONY: lint
lint: pylint flake8

.PHONY: checkstyle
checkstyle: black lint

.PHONY: test
test: only-test checkstyle
