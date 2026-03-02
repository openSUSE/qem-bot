# Product Guidelines: qem-bot

## Prose Style
All project documentation, log messages, and error reports must follow a **Technical & Objective** tone. This means being precise, direct, and focused on the technical implementation or data being processed. Avoid conversational filler or ambiguity.

## CLI Visuals
The bot's CLI output should prioritize a **Minimalist & Streamlined** visual style. Since the bot is primarily executed in headless environments (e.g., GitLab CI pipelines), the output must be clean, easy to parse, and avoid excessive interactive elements or rich text that could clutter log files.

## UX Principles
The primary user experience for `qem-bot` is through the inspection of its execution logs after a headless run.
- **Observability-First:** Every action taken by the bot must be logged with enough context so that a QA Engineer can understand the bot's state and decisions by inspecting the output.
- **Actionable Error Reporting:** When an error occurs, the bot should provide a clear, technical explanation of what went wrong and, where possible, include actionable remediation steps.
- **Headless Optimization:** Design for non-interactive execution, ensuring that all necessary information is captured without requiring user input.

## Documentation Guidelines
Documentation should follow the project's established conventions:
- **Pragmatic Docstrings:** Use inline docstrings to explain the "why" and complex logic, rather than repeating what the code already expresses. Avoid verbose comments that are redundant to the code's implementation.
- **System Documentation:** Maintain high-level architectural and usage details in external Markdown files (e.g., in the `doc/` directory) to provide a clear entry point for users and developers.
- **Reviewer Consideration:** Be mindful of the level of detail in PRs, ensuring that comments add value and aid in the review process without being overwhelming.
