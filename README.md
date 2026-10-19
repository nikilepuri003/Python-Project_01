# CodePulse AI

CodePulse AI is a professional observability and AI-assisted incident response MVP for monitoring distributed APIs and microservices.

## Current status

The frontend supports Google sign-in, per-user accounts, manual one-off website checks, scheduled monitors, check history, persisted incidents, diagnosis, a demo patch proposal, and an explicit draft-PR action. Patch generation is currently limited to the included payment-service demo. Validation applies the patch in a disposable workspace, checks its Python syntax and timeout-fallback structure, then runs backend tests with a 120-second limit. It is not an operating-system sandbox; only the deterministic server-side patch and approved demo paths are accepted. GitHub creates a real draft PR only after validation and a successful authorized API response; otherwise the dashboard reports mock/not-configured status without a fake URL.

## Quick start

### Google sign-in

Set the same Google OAuth client ID in `frontend/.env.local` as `VITE_GOOGLE_CLIENT_ID` and in `backend/.env` (or the backend process environment) as `GOOGLE_CLIENT_ID`. For Docker Compose, provide both variables in the root `.env` file. Add the frontend origin (for local development, `http://localhost:5173`) to the OAuth client's **Authorized JavaScript origins** in Google Cloud Console. Restart the frontend and backend after changing environment values.

The frontend shows a Google sign-in screen before loading the dashboard. New users can continue with Google from the same button; their Google identity creates a persistent account on first sign-in. Local development defaults to SQLite at `backend/codepulse.db`; production must set `DATABASE_URL` to a persistent PostgreSQL database.

Draft public policy pages are served at `/privacy.html` and `/terms.html`. They are marked for owner review and must be approved before adding them to Google OAuth branding or publishing the OAuth app.

### Check a website's health

After signing in, enter a public website URL and choose **Check website**. The backend makes one HTTP(S) request (10-second timeout, without following redirects) and reports the observed HTTP status, reachability, and response time. A successful HTTP response only confirms that URL responded; it does not verify the website's database or other internal services. Private/local network addresses are rejected.

### Scheduled monitors and incidents

From the signed-in dashboard, add, edit, pause, resume, or delete up to 20 public HTTP(S) monitors, or select one of the fixed demo services when running the Docker Compose stack. Checks run at the selected interval (60 seconds to 24 hours), and the dashboard can show the latest result and recent history. A 5xx response, two consecutive non-healthy results, or a check taking at least five seconds opens or updates a persisted incident; a successful check resolves an open incident. Public checks pin connections to DNS-resolved public IPs, reject non-public/reserved destinations and unsafe ports, and do not follow redirects. Demo checks are restricted to three hard-coded Docker service names/ports and only accept private DNS results.

The scheduler runs inside the FastAPI process. PostgreSQL advisory locking prevents multiple backend instances from running duplicate scheduler loops; local SQLite is intended for one backend process. Free hosting that sleeps cannot provide dependable continuous checks. Check history is limited to the most recent 1,000 checks per monitor; resolved incidents are retained up to 100 per monitor and for at most 90 days. Open incidents are retained until resolved.

Monitoring endpoints require the same Bearer session token used by the frontend. See [docs/api.md](docs/api.md) for the API surface.

### Incident diagnosis, patch validation, and draft PR

For an open incident on a monitor named `payment-service`, request a diagnosis, then choose **Propose and validate demo patch**. The deterministic demo patch changes `services/payment_service/main.py`; other monitor names are intentionally not mapped to arbitrary source code. The backend applies it in a temporary copy, verifies the approved target and expected timeout-fallback structure, and runs backend tests with a 120-second timeout. The diff and results are shown before any GitHub action.

To create a real draft PR, configure `GITHUB_TOKEN`, `GITHUB_OWNER`, `GITHUB_REPOSITORY`, and `GITHUB_BASE_BRANCH` on the backend. Use a fine-grained token restricted to the intended repository with **Contents: Read and write** and **Pull requests: Read and write**. Keep the token server-side; never add it to the frontend or paste it into chat. The service re-checks that the diff applies to the configured base branch, creates a branch and commit through GitHub's Git Database API, then requests a draft PR. It does not merge or deploy. If configuration is absent, it reports mock/not-configured and creates no branch, commit, PR, or fake link.

The included patch template is a demo-only example, not a diagnosis-specific production repair. Review its diff and validation results before requesting a PR. Validation uses an ephemeral copy and fixed Git/pytest commands with timeouts, but is not an OS/container security boundary.

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

### Docker Compose

```bash
docker compose up --build
```

### Deploy on Render

The root `render.yaml` deploys the frontend as a static site and the FastAPI backend as a free web service. Persistent user accounts require a PostgreSQL database: create one in Render and set the backend service's `DATABASE_URL` to its **internal** connection string. Use a paid database plan for accounts that must not expire; Render's free database plans may have limited lifetime and no production guarantees.

1. Push the project to GitHub.
2. In Render, create a new Blueprint and select this repository. Render reads `render.yaml` from the repository root.
3. When prompted, enter the same Google OAuth client ID for `GOOGLE_CLIENT_ID` and `VITE_GOOGLE_CLIENT_ID`.
4. After deployment, add the frontend's `onrender.com` URL to the OAuth client's **Authorized JavaScript origins** in Google Cloud Console.

Free Render web services spin down after 15 minutes without traffic, so the first request after inactivity can take about a minute. This is suitable for a demo, not production.

The in-process monitor scheduler only runs while the backend is awake. For dependable scheduling, deploy an always-on backend/worker with a persistent PostgreSQL database. The temporary Free Render database used by the current deployment has a scheduled expiration; upgrade or migrate it before that date if account and monitor data must be retained.

### Demo: end-to-end incident lifecycle

```bash
python scripts/reset_demo.py
python scripts/create_demo_failure.py --mode database_timeout --apply
python scripts/seed_data.py --base-url http://localhost:8000
```

This runs the detection -> evidence -> anomaly -> diagnosis -> patch -> validation -> GitHub metadata flow in the running prototype.

## Notes

The prototype stays intentionally safe: it creates diagnosis metadata and patch proposals rather than making destructive repository changes without human review.
