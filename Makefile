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

VENV = qem-bot
.PHONY environment:
	if [ ! -d "$(VENV)" ]; then virtualenv -p python3 $(VENV); fi
	. $(VENV)/bin/activate && pip install -r requirements-dev.txt -r requirements.txt

# Developers have bad memory, so we need to remind them to activate the virtualenv
# maybe use Makefile.VENV instead to get a shell with virtualenv
# .PHONY devel: environment
# 	# we need to detect what shell we are using
# 	shell=$$(basename $$SHELL); \
# 	echo "Activating virtualenv for $$shell"; \
# 	. $(VENV) && \
# 	exec $($(SHELL))
