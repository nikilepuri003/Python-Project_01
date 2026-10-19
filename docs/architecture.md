# Architecture

- React, TypeScript, and Vite provide the sign-in and monitoring dashboard.
- FastAPI provides Google authentication, public URL checks, user-owned monitor APIs, diagnosis prototypes, and Prometheus request metrics.
- SQLAlchemy persists user accounts/sessions, monitor definitions, check history, and monitor incidents in SQLite locally or PostgreSQL in production.
- A background thread in the API process runs due checks. PostgreSQL advisory locking elects one scheduler instance; local SQLite is for a single API process.
- Outbound monitor requests resolve and validate public addresses, connect to a pinned address, limit checks to HTTP/HTTPS ports 80/443, and do not follow redirects.
- Docker Compose provides local demo microservices, PostgreSQL, and Prometheus.

The deployed dashboard now supports per-user scheduled monitors and incident evidence. The separate original incident workflow contains detection, anomaly, diagnosis, patch-proposal, validation, and GitHub prototype modules. Those modules are not yet a secure, automated, end-to-end production patch/PR workflow, and demo scenario data must not be mistaken for live telemetry.
