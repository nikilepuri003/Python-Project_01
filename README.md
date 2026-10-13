# CodePulse AI

CodePulse AI is a professional observability and AI-assisted incident response MVP for monitoring distributed APIs and microservices.

## Current phases

The project has already implemented the backend detection, diagnosis, patching, validation, GitHub metadata, and frontend dashboard phases. The remaining work is to finish the operational demo and live stack validation.

## Quick start

### Google sign-in

Set the same Google OAuth client ID in `frontend/.env.local` as `VITE_GOOGLE_CLIENT_ID` and in `backend/.env` (or the backend process environment) as `GOOGLE_CLIENT_ID`. For Docker Compose, provide both variables in the root `.env` file. Add the frontend origin (for local development, `http://localhost:5173`) to the OAuth client's **Authorized JavaScript origins** in Google Cloud Console. Restart the frontend and backend after changing environment values.

The frontend shows a Google sign-in screen before loading the dashboard. New users can continue with Google from the same button.

### Check a website's health

After signing in, enter a public website URL and choose **Check website**. The backend makes one HTTP(S) request (10-second timeout, without following redirects) and reports the observed HTTP status, reachability, and response time. A successful HTTP response only confirms that URL responded; it does not verify the website's database or other internal services. Private/local network addresses are rejected.

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

### Demo: end-to-end incident lifecycle

```bash
python scripts/reset_demo.py
python scripts/create_demo_failure.py --mode database_timeout --apply
python scripts/seed_data.py --base-url http://localhost:8000
```

This runs the detection -> evidence -> anomaly -> diagnosis -> patch -> validation -> GitHub metadata flow in the running prototype.

## Notes

The prototype stays intentionally safe: it creates diagnosis metadata and patch proposals rather than making destructive repository changes without human review.
