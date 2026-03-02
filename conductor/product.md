# Product Guide: qem-bot

## Initial Concept
`qem-bot` is a tool for scheduling maintenance tests on openQA based on various submission sources (SMELT, Gitea, OBS) and synchronizing results with the `qem-dashboard`. It automates the testing and approval workflow for maintenance incidents and product increments.

## Target Audience
The primary users of `qem-bot` are **QA Engineers & Release Managers** who rely on its automated status reporting and approvals in OBS and Gitea.

## Core Goals
The main objectives of `qem-bot` are:
1. **Automate Maintenance Testing:** Efficiently schedule openQA tests for submissions, aggregates, and product increments.
2. **Synchronize Results:** Ensure that `qem-dashboard` accurately reflects the state of all openQA jobs.
3. **Streamline Approvals:** Automatically approve incidents and product increments once testing criteria are met.

## Success Metrics
The effectiveness of the bot is measured by:
- **Reduction in Approval Turnaround Time:** Faster transitions from submission to approval.
- **Data Accuracy & Reliability:** Ensuring that all reported test results and approval statuses are correct.

## Key Features
- **Submission Source Integration:** Unified handling of SMELT incidents, Gitea Pull Requests, and OBS product increments.
- **Dynamic Scheduling:** Triggering openQA jobs based on specific metadata and configuration.
- **Result Synchronization:** Bidirectional communication between openQA, OBS, and the `qem-dashboard`.
- **Automated Approval Logic:** Policy-driven approvals based on test success.

## Constraints & Challenges
- **Job Trigger Reliability:** The most critical challenge is ensuring that openQA jobs are triggered reliably and correctly according to the project's metadata specifications.
