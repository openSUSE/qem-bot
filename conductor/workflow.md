# Project Workflow

## Guiding Principles

1. **The Plan is the Source of Truth:** All work must be tracked in `plan.md`
2. **The Tech Stack is Deliberate:** Changes to the tech stack must be documented in `tech-stack.md` *before* implementation
3. **Test-Driven Development:** Write unit tests before implementing functionality
4. **Full Code Coverage:** Ensure 100% statement and branch coverage for all modules
5. **User Experience First:** Every decision should prioritize user experience
6. **Non-Interactive & CI-Aware:** Prefer non-interactive commands. Use `CI=true` for watch-mode tools (tests, linters) to ensure single execution.

## Task Workflow

All tasks follow a strict lifecycle:

### Standard Task Workflow

1. **Select Task:** Choose the next available task from `plan.md` in sequential order

2. **Mark In Progress:** Before beginning work, edit `plan.md` and change the task from `[ ]` to `[~]`

3. **Write Failing Tests (Red Phase):**
   - Create a new test file for the feature or bug fix.
   - Write one or more unit tests that clearly define the expected behavior and acceptance criteria for the task.
   - **CRITICAL:** Run the tests and confirm that they fail as expected. This is the "Red" phase of TDD. Do not proceed until you have failing tests.

4. **Implement to Pass Tests (Green Phase):**
   - Write the minimum amount of application code necessary to make the failing tests pass.
   - Run the test suite again and confirm that all tests now pass. This is the "Green" phase.

5. **Refactor (Optional but Recommended):**
   - With the safety of passing tests, refactor the implementation code and the test code to improve clarity, remove duplication, and enhance performance without changing the external behavior.
   - Rerun tests to ensure they still pass after refactoring.

6. **Verify Coverage:** Run coverage reports using the project's chosen tools.
   ```bash
   uv run make test-with-coverage
   ```
   Target: 100% coverage.

7. **Document Deviations:** If implementation differs from tech stack:
   - **STOP** implementation
   - Update `tech-stack.md` with new design
   - Add dated note explaining the change
   - Resume implementation

8. **Commit Code Changes:**
   - Run `uv run make tidy` to format code.
   - Stage all code changes related to the task.
   - Propose a clear, concise commit message e.g, `feat(ui): Create basic HTML structure for calculator`.
   - Perform the commit.

9. **Attach Task Summary with Git Notes:**
   - **Step 9.1: Get Commit Hash:** Obtain the hash of the *just-completed commit* (`git log -1 --format="%H"`).
   - **Step 9.2: Draft Note Content:** Create a detailed summary for the completed task. This should include the task name, a summary of changes, a list of all created/modified files, and the core "why" for the change.
   - **Step 9.3: Attach Note:** Use the `git notes` command to attach the summary to the commit.
     ```bash
     git notes add -m "<note content>" <commit_hash>
     ```

10. **Get and Record Task Commit SHA:**
    - **Step 10.1: Update Plan:** Read `plan.md`, find the line for the completed task, update its status from `[~]` to `[x]`, and append the first 7 characters of the *just-completed commit's* commit hash.
    - **Step 10.2: Write Plan:** Write the updated content back to `plan.md`.

11. **Commit Plan Update:**
    - **Action:** Stage the modified `plan.md` file.
    - **Action:** Commit this change with a descriptive message (e.g., `conductor(plan): Mark task 'Create user model' as complete`).

### Phase Completion Verification and Checkpointing Protocol

**Trigger:** This protocol is executed immediately after a task is completed that also concludes a phase in `plan.md`.

1.  **Announce Protocol Start:** Inform the user that the phase is complete and the verification and checkpointing protocol has begun.

2.  **Ensure Test Coverage for Phase Changes:**
    -   **Step 2.1: Determine Phase Scope:** Identfiy scope since last checkpoint.
    -   **Step 2.2: List Changed Files:** `git diff --name-only <previous_checkpoint_sha> HEAD`
    -   **Step 2.3: Verify and Create Tests:** Ensure every modified code file has corresponding tests reaching 100% coverage.

3.  **Execute Automated Tests with Proactive Debugging:**
    -   Execute `uv run make checkstyle typecheck-ty test-with-coverage`.
    -   If tests fail, debug (max 2 attempts) before reporting to user.

4.  **Propose a Detailed, Actionable Manual Verification Plan:** Generate a step-by-step plan based on `product.md` and `plan.md`.

5.  **Await Explicit User Feedback:** Pause for user confirmation.

6.  **Create Checkpoint Commit:** `git commit --allow-empty -m "conductor(checkpoint): Checkpoint end of Phase X"`

7.  **Attach Auditable Verification Report using Git Notes:** Attach summary via `git notes`.

8.  **Get and Record Phase Checkpoint SHA:** Record in `plan.md`.

9. **Commit Plan Update:** `git commit -m "conductor(plan): Mark phase '<PHASE NAME>' as complete"`

10.  **Announce Completion:** Inform the user.

### Quality Gates

Before marking any task complete, verify:

- [ ] All tests pass
- [ ] Code coverage is 100%
- [ ] `uv run make tidy` has been executed
- [ ] `uv run make checkstyle` and `uv run make typecheck-ty` pass
- [ ] All public functions/methods are documented
- [ ] Type safety is enforced
- [ ] No security vulnerabilities introduced

## Development Commands

### Setup
```bash
uv sync
```

### Daily Development
```bash
# Format code
uv run make tidy

# Run tests
uv run make test

# Full checkstyle (ruff, radon, vulture, ty)
uv run make checkstyle

# Type checking
uv run make typecheck-ty
```

### Before Committing
```bash
uv run make tidy checkstyle typecheck-ty test-with-coverage
```

## Testing Requirements

### Unit Testing
- Every module must have corresponding tests.
- Mock external dependencies (openQA, OBS, Gitea, SMELT, Dashboard).
- Test both success and failure cases.
- **Target: 100% statement and branch coverage.**

## Code Review Process

### Self-Review Checklist
Before requesting review:

1. **Functionality**
   - Feature works as specified
   - Edge cases handled

2. **Code Quality**
   - Follows style guide
   - DRY principle applied
   - No dead code (verified by `vulture`)
   - Maintainability index >= 70 (verified by `radon`)

3. **Testing**
   - Unit tests comprehensive
   - Coverage is 100%

4. **Security**
   - No hardcoded secrets
   - Banned patterns (e.g., `os.system`) avoided

## Commit Guidelines

### Message Format
```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Formatting, missing semicolons, etc.
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `test`: Adding missing tests
- `chore`: Maintenance tasks
