SOURCE_FILES ?= $(shell git ls-files "**.py")
USE_TY_TYPECHECK ?= 0
ISOLATE ?= 1

ifeq ($(ISOLATE),1)
UNSHARE := unshare -r -n
else
UNSHARE :=
endif

.PHONY: help
help: ## Display this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.PHONY: all
all: help

# Detect if pytest-xdist is installed for parallel testing
PYTEST_XDIST := $(shell python3 -m pytest --version 2>&1 | grep -q xdist && echo "-n auto" || echo "")

.PHONY: only-test
only-test: ## Run unit tests without style checks
	$(UNSHARE) python3 -m pytest $(PYTEST_XDIST)

.PHONY: ruff
ruff: ## Run ruff linting and formatting checks
	ruff check
	ruff format --check

.PHONY: tidy
tidy: ## Format code and fix linting issues
	ruff format
	ruff check --fix

.PHONY: check-conventions
check-conventions: ## Check for banned coding patterns
	@if git grep -nE '^\s*@(unittest\.mock\.|mock\.)?patch' tests/; then \
		echo "Error: @patch decorator detected. Avoid to prevent argument ordering bugs."; \
		echo "   Fix: Use the 'mocker' fixture (pytest-mock) or a 'with patch():' context manager."; \
		exit 1; \
	fi

.PHONY: check-maintainability
check-maintainability: ## Check maintainability index (radon)
	@echo "Checking maintainability (grade B or worse) …"
	@radon mi ${SOURCE_FILES} -n B | (! grep ".")

.PHONY: check-code-health
check-code-health: ## Find dead code (vulture)
	@echo "Checking code health…"
	@vulture ${SOURCE_FILES} --min-confidence 80

.PHONY: typecheck-pyright
typecheck-pyright: ## Run pyright type checker
	PYRIGHT_PYTHON_FORCE_VERSION=latest pyright --skipunannotated --warnings

.PHONY: typecheck-ty
typecheck-ty: ## Run ty type checker
	ty check
.PHONY: only-test-with-coverage

.PHONY: typecheck
ifeq ($(USE_TY_TYPECHECK),0)
# Using pyright for typechecking as part of top-level target due to easier
# dependencies. ty is recommended if available to you
typecheck_target = typecheck-pyright
else
typecheck_target = typecheck-ty
endif
typecheck: $(typecheck_target) ## Run default type checker

only-test-with-coverage: ## Run unit tests with coverage report
	$(UNSHARE) python3 -m pytest $(PYTEST_XDIST) -v --cov --cov-report=xml --cov-report=term-missing

# aggregate targets

.PHONY: checkstyle
checkstyle: ruff check-conventions check-maintainability check-code-health typecheck ## Run all style and static analysis checks

.PHONY: test
test: only-test checkstyle ## Run all tests and style checks

.PHONY: test-with-coverage
test-with-coverage: only-test-with-coverage checkstyle ## Run tests with coverage and style checks

BOT_COMMANDS ?= $(shell python3 ./qem-bot.py --help | grep '{.*}' | head -n 1 | sed -n 's/.*{\(.*\)}.*/\1/p' | tr ',' ' ')

.PHONY: test-all-commands-unstable
test-all-commands-unstable: ## Test all bot commands with fake data
	for i in $(BOT_COMMANDS); do \
		echo "### $$i" && \
		timeout --foreground 30 $(UNSHARE) python3 ./qem-bot.py -t 1234 -c metadata/qem-bot --singlearch metadata/qem-bot/singlearch.yml --dry --fake-data $$i || \
		{ ret=$$?; [ $$ret -eq 124 ] || [ $$ret -eq 0 ] || exit $$ret; }; \
	done

.PHONY: setup-hooks
setup-hooks: ## Install pre-commit git hooks
	pre-commit install --install-hooks -t commit-msg -t pre-commit

.PHONY: update-readme
update-readme: ## Update CLI usage section in Readme.md
	python3 scripts/update_readme.py
