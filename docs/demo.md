# Demo Workflow

## Scheduled website checks

1. Start the backend and frontend (or `docker compose up --build`) and sign in with Google.
2. Add a public HTTP(S) website on the signed-in dashboard; select a check interval of at least 60 seconds.
3. Use **Check now** to create an immediate persisted check, or keep the monitor enabled for the scheduler.
4. For a local, non-production test, point a monitor at a controlled public test endpoint that returns HTTP 503 or is unreachable. A 5xx opens an incident immediately; other non-healthy results open one after two consecutive failures. A successful result resolves an open incident.
5. Review the evidence and request a diagnosis. Without a valid server-side AI provider key, the result is labeled as mock demo output.

The checker only probes the public HTTP response; it does not inspect a website's database or internal services. Never use a URL that exposes private infrastructure.

## Demo incident-to-draft-PR lifecycle

1. Run the local Docker Compose stack, sign in, and select the included **Payment Service** demo monitor (or use a controlled public endpoint).
2. To simulate an outage, stop the demo service and use **Check now** twice; review the resulting incident and request its diagnosis. Restart the demo service after the exercise.
3. Choose **Propose and validate demo patch**. The backend generates the deterministic demo-only patch, applies it in a disposable copy, checks the timeout branch and syntax, and runs backend tests with a timeout. The UI displays the full diff and results. Failed validation blocks PR creation.
4. Configure a least-privilege GitHub token and target repository on the backend. Review the diff, then explicitly choose **Create draft PR**. The backend rechecks that the diff applies to the current base branch and records the confirmed draft PR URL only after GitHub succeeds.
5. Without GitHub configuration, the dashboard reports mock/not-configured status and no PR URL is fabricated. No PR is merged or deployed.

The patch template deliberately supports only the included payment-service demo; it is not a general-purpose repair for arbitrary monitored websites. Legacy synthetic detection/anomaly scenario APIs remain demo-only and are not live telemetry.
