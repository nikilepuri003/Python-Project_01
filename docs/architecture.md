# Architecture

This project follows a modular full-stack architecture with:

- FastAPI backend for incident APIs and orchestration
- React frontend for observability dashboard
- Docker Compose for local orchestration
- Prometheus for metric scraping
- OpenTelemetry for trace collection

The repository is intentionally structured so future phases can add service-specific logic without breaking the overall platform.
