# Technology Stack: qem-bot

## Core Language
- **Python (>=3.9):** The primary language used for developing the bot, leveraging modern features and type hinting for reliability.

## Key Frameworks & Libraries
- **CLI Development:** `typer` is used for creating the command-line interface, providing a robust and user-friendly experience.
- **API & Networking:**
    - `requests`: For interacting with external APIs (SMELT, Gitea, Dashboard).
    - `pika`: For AMQP-based communication (listening for events).
- **Integration Tools:**
    - `osc`: For communicating with the Open Build Service (OBS).
    - `openqa-client`: For scheduling and managing jobs on openQA.
- **Data Handling:**
    - `ruamel.yaml` & `PyYAML`: For parsing and writing configuration files.
    - `lxml`: For handling XML data from OBS and other sources.
    - `pydantic-settings`: For managing configuration via environment variables.

## Development & Testing Tooling
- **Dependency Management:** `uv` is the recommended tool for managing dependencies and virtual environments.
- **Testing:**
    - `pytest`: The core testing framework.
    - `pytest-cov`: For measuring code coverage (target: 100%).
    - `responses`: For mocking HTTP requests in tests.
    - `pytest-mock`: For mocking and patching in tests.
- **Linting & Formatting:** `ruff` is used for fast and comprehensive linting and formatting.
- **Type Checking:** `ty` is used for static type analysis.

## Infrastructure & Deployment
- **Execution:** Primarily runs as scheduled jobs in GitLab CI pipelines.
- **Environment Management:** Configuration is managed through a mix of YAML files and environment variables (via `python-dotenv`).
