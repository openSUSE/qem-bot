SOURCE_FILES ?= $(shell git ls-files "**.py")
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
PYTEST_XDIST := $(shell python3 -c "import xdist" 2>/dev/null && echo "-n auto" || echo "")

.PHONY: only-test
only-test: ## Run dynamic tests with coverage report
	$(UNSHARE) python3 -m pytest $(PYTEST_XDIST) -v --cov --cov-report=xml --cov-report=term-missing

.PHONY: only-test-no-coverage
only-test-no-coverage: ## Run dynamic tests without coverage analysis and without style checks
	$(UNSHARE) python3 -m pytest $(PYTEST_XDIST)

.PHONY: only-test-with-coverage
only-test-with-coverage: only-test  ## Alias for "only-test"

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

.PHONY: check-code-health
check-code-health: ## Find dead code (vulture)
	@echo "Checking code health…"
	@vulture ${SOURCE_FILES} --min-confidence 80

.PHONY: check-maintainability
check-maintainability: ## Check maintainability index (radon)
	@echo "Checking maintainability (grade B or worse) …"
	@radon mi ${SOURCE_FILES} -n B | (! grep ".")

.PHONY: typecheck-ty
typecheck-ty: ## Run ty type checker
	ty check

.PHONY: typecheck
typecheck: typecheck-ty

# aggregate targets

.PHONY: checkstyle
checkstyle: ## Run fast style and static analysis checks
	@$(MAKE) -j ruff check-conventions typecheck

.PHONY: checkstyle-all
checkstyle-all: ## Run all style and static analysis checks
	@$(MAKE) -j checkstyle check-code-health check-maintainability

.PHONY: test
test: ## Run all tests with coverage analysis and style checks
	@$(MAKE) -j only-test-with-coverage checkstyle-all

.PHONY: test-no-coverage
test-no-coverage: ## Run all tests *without* coverage analysis and style checks (faster)
	@$(MAKE) -j only-test checkstyle-all

.PHONY: test-with-coverage
test-with-coverage: test  ## Alias for "test"

BOT_COMMANDS ?= $(shell python3 -c "from openqabot.args import app; from typer.main import get_command_name; print(' '.join(get_command_name(c.name or c.callback.__name__) for c in app.registered_commands if not c.hidden))")
TIMEOUT ?= 30
QEM_DASHBOARD_URL ?= "http://localhost:3000/"
GITEA_TOKEN_CMD ?= cat ./.gitea_token
TEST_QEM_BOT_INTEGRATION_ARGS ?= -t s3cret -c metadata/qem-bot --singlearch metadata/qem-bot/singlearch.yml --gitea-token $$($(GITEA_TOKEN_CMD)) --retry 0
TEST_QEM_BOT_INTEGRATION_EXTRA_ARGS ?=
QEM_BOT_BASE_CMD = env QEM_DASHBOARD_URL=$(QEM_DASHBOARD_URL) python3 ./qem-bot.py $(TEST_QEM_BOT_INTEGRATION_ARGS) $(TEST_QEM_BOT_INTEGRATION_EXTRA_ARGS)

.PHONY: test-all-commands-unstable
test-all-commands-unstable: ## Test all bot commands with fake data
	for i in $(BOT_COMMANDS); do \
		echo "### $$i" && \
		timeout --foreground $(TIMEOUT) $(UNSHARE) $(QEM_BOT_BASE_CMD) --dry --fake-data $$i || \
		{ ret=$$?; [ $$ret -eq 124 ] || [ $$ret -eq 0 ] || exit $$ret; }; \
	done

.PHONY: run-dashboard-local
run-dashboard-local:  ## Run a qem-dashboard instance for testing from ../qem-dashboard (Needs to be checked out manually)
	make -C ../qem-dashboard run-dashboard-local

.PHONY: check_for_dashboard
check_for_dashboard:  ## Check for a responsive qem-dashboard instance for testing
	@curl -s -o /dev/null -w "%{http_code}\n" $(QEM_DASHBOARD_URL) || { echo "No responsive server found on $(QEM_DASHBOARD_URL). Make sure to start a qem-dashboard manually or with 'make run-dashboard-local'" ; exit 1; }

.PHONY: test-dashboard-integration
test-dashboard-integration: check_for_dashboard  ## Test qem-bot against a local dashboard instance
	$(QEM_BOT_BASE_CMD) gitea-sync
	$(QEM_BOT_BASE_CMD) smelt-sync
	$(QEM_BOT_BASE_CMD) --dry submissions-run
	$(QEM_BOT_BASE_CMD) --dry sub-approve

.PHONY: setup-hooks
setup-hooks: ## Install pre-commit git hooks
	pre-commit install --install-hooks -t commit-msg -t pre-commit

.PHONY: update-readme
update-readme: ## Update CLI usage section in Readme.md
	python3 scripts/update_readme.py
