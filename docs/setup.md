# Setup Guide

Use the environment template in `.env.example` before starting the application.

1. Copy `.env.example` to `.env`.
2. Install backend dependencies.
3. Install frontend dependencies.
4. Run the backend and frontend locally.
5. Run the full Docker Compose stack when ready.

The API process runs the monitoring scheduler by default. Set `MONITOR_SCHEDULER_ENABLED=false` to disable it. SQLite is intended for one local backend process; PostgreSQL advisory locking elects a single scheduler when multiple production API instances use the same database.

Scheduled monitoring is only dependable while the backend process is running. Free/sleeping hosting is not a production scheduler. For continuous checks, use an always-on worker/API process and persistent PostgreSQL.

## Optional GitHub draft PR integration

Set `GITHUB_TOKEN`, `GITHUB_OWNER`, `GITHUB_REPOSITORY`, and `GITHUB_BASE_BRANCH` on the backend only. Use a fine-grained token restricted to the selected repository with Contents read/write and Pull requests read/write permissions. Do not expose the token to Vite or the browser. The app creates only a draft PR after a proposal passes validation; it never merges or deploys. Without configuration, it reports mock/not-configured mode and does not create a fake PR link.

The remediation workflow is intentionally limited to the included `payment-service` demo and a deterministic timeout-to-queued patch. It refuses other monitor names and paths rather than guessing how to modify an arbitrary website's source. Patch validation applies the patch in a temporary workspace, statically checks the change, and runs backend tests with a 120-second timeout; it is not a container or OS security sandbox. The demo patch changes response behavior and requires human review.
