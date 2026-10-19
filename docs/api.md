# API Overview

The backend exposes versioned APIs under `/api/v1`, with service health at `/health` and `/ready` and Prometheus metrics at `/metrics`.

## Authentication

- `POST /api/v1/auth/google` verifies a Google ID token and creates/updates the user's account and session.
- `GET /api/v1/auth/me` returns the current session's user.
- `POST /api/v1/auth/logout` revokes the current session.

## User-owned monitoring

Every endpoint below requires `Authorization: Bearer <session_token>`. Monitor records, check history, and incidents are scoped to the authenticated user.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/v1/monitors` | List this user's monitors with their latest check |
| `GET` | `/api/v1/monitoring/demo-services` | List fixed included demo service targets |
| `POST` | `/api/v1/monitors` | Add a public HTTP(S) monitor (`name`, `url`, optional `interval_seconds`) |
| `PATCH` | `/api/v1/monitors/{id}` | Edit name/URL/interval or enable/pause |
| `DELETE` | `/api/v1/monitors/{id}` | Delete a monitor and its check/incident records |
| `POST` | `/api/v1/monitors/{id}/check` | Run and persist an immediate check |
| `GET` | `/api/v1/monitors/{id}/checks` | List up to 100 recent checks (default 50) |
| `GET` | `/api/v1/monitoring/incidents` | List this user's recent incidents |
| `POST` | `/api/v1/monitoring/incidents/{id}/diagnose` | Generate and persist a structured diagnosis |
| `POST` | `/api/v1/monitoring/incidents/{id}/patch` | Propose the supported demo patch, validate it in a disposable workspace, and persist results |
| `POST` | `/api/v1/monitoring/incidents/{id}/draft-pr` | Create a draft PR only for a persisted patch that passed validation |
| `GET` | `/api/v1/monitoring/github-status` | Report real or mock/not-configured GitHub state without exposing credentials |

Intervals must be between 60 seconds and 24 hours. Each account may create at most 20 monitors. Only HTTP and HTTPS on ports 80 and 443 are allowed. The checker rejects non-public DNS/IP destinations, connects to a validated IP while retaining the original host/TLS name, and does not follow redirects.

Monitor creation also accepts one exact fixed demo URL (`demo://payment-service`, `demo://order-service`, or `demo://user-service`). These are not arbitrary hostnames: the checker maps each ID to a fixed Docker Compose service name and port, rejects resolution outside private addresses, requests only `/health`, and does not follow redirects. They are intended only for the included local Docker Compose network; they may be unreachable on other hosting.

The background scheduler runs in the backend process every five seconds and checks due monitors. A PostgreSQL advisory lock elects one scheduler instance. SQLite is supported for single-process local development only. Sleeping/free hosting cannot guarantee scheduled checks.

Check history is capped at 1,000 records per monitor. Resolved incidents are capped at 100 per monitor and 90 days; open incidents are not age-pruned.

The existing one-off `POST /api/v1/monitor/probe` endpoint remains available without a session for compatibility with the original manual check. It does not create a monitor or retain history.

Patch generation currently supports incidents for a monitor named `payment-service` and targets exactly `services/payment_service/main.py`. Validation checks a single-file unified diff, applies it in a temporary copy, checks the expected timeout-fallback structure and Python syntax, and runs backend tests with a 120-second timeout. A failed validation is persisted and blocks PR creation. This is not an OS-level sandbox; only a deterministic server-side template and approved demo path are accepted.

GitHub settings are server-side only: `GITHUB_TOKEN`, `GITHUB_OWNER`, `GITHUB_REPOSITORY`, and `GITHUB_BASE_BRANCH`. Use a fine-grained token restricted to the selected repository with Contents read/write and Pull requests read/write permissions. The API re-fetches the configured base file and refuses the PR if the patch no longer applies. Mock mode returns no URL and performs no GitHub writes. API failures are reported as failures. The application never merges or deploys.

Legacy direct `/api/v1/github/branch`, `/api/v1/github/commit`, and `/api/v1/github/pr` prototype endpoints return `410 Gone`; unvalidated branch, commit, and PR operations are disabled. Older synthetic detection/anomaly scenario endpoints remain demo-only and are not live telemetry.
