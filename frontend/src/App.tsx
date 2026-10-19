import { useEffect, useState, type FormEvent } from 'react';

type UserProfile = {
  sub: string;
  email: string;
  name: string;
  picture: string;
  role: string;
};

type GoogleCredentialResponse = {
  credential: string;
};

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (options: {
            client_id: string;
            callback: (response: GoogleCredentialResponse) => void;
          }) => void;
          renderButton: (element: HTMLElement, options: Record<string, string | number>) => void;
        };
      };
    };
  }
}

type ProbeResult = {
  url: string;
  result: 'healthy' | 'redirect' | 'client_error' | 'server_error' | 'unavailable';
  reachable: boolean;
  status_code: number | null;
  response_time_ms: number;
  message: string;
  checked_at: string;
};

type MonitorCheck = {
  id: number;
  result: string;
  reachable: boolean;
  status_code: number | null;
  response_time_ms: number;
  message: string;
  checked_at: string;
};

type Monitor = {
  id: number;
  name: string;
  url: string;
  interval_seconds: number;
  enabled: boolean;
  consecutive_failures: number;
  latest_check: MonitorCheck | null;
};

type DemoService = {
  id: string;
  name: string;
  url: string;
};

type MonitorIncident = {
  id: number;
  monitor_id: number;
  title: string;
  status: string;
  severity: string;
  evidence: Record<string, unknown>;
  diagnosis: Record<string, unknown> | null;
  diagnosis_provider: string | null;
  patch_proposal: PatchProposal | null;
  created_at: string;
};

type PatchProposal = {
  id: string;
  service: string;
  summary: string;
  file_path: string;
  diff: string;
  confidence: number;
  risks: string[];
  validation_status: 'passed' | 'failed' | 'pending';
  validation: {
    passed: boolean;
    checks: string[];
    summary: string;
    details: Record<string, string>;
  };
  github_result: {
    status: string;
    source: 'github' | 'mock';
    draft: boolean;
    url: string | null;
    number?: number;
    error?: string;
    note?: string;
  } | null;
  created_at: string;
};

type GitHubStatus = {
  mode: 'real' | 'mock';
  configured: boolean;
  repository: string | null;
  base_branch: string | null;
};

export default function App() {
  const configuredApiUrl = import.meta.env.VITE_API_URL as string | undefined;
  const apiUrl = (
    configuredApiUrl
      ? (/^https?:\/\//i.test(configuredApiUrl) ? configuredApiUrl : `https://${configuredApiUrl}`)
      : 'http://localhost:8000'
  ).replace(/\/+$/, '');
  const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;
  const [user, setUser] = useState<UserProfile | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState('');
  const [authNotice, setAuthNotice] = useState('');
  const [googleButtonElement, setGoogleButtonElement] = useState<HTMLDivElement | null>(null);
  const [websiteUrl, setWebsiteUrl] = useState('');
  const [probeResult, setProbeResult] = useState<ProbeResult | null>(null);
  const [probeError, setProbeError] = useState('');
  const [probing, setProbing] = useState(false);
  const [monitors, setMonitors] = useState<Monitor[]>([]);
  const [incidents, setIncidents] = useState<MonitorIncident[]>([]);
  const [monitorName, setMonitorName] = useState('');
  const [monitorUrl, setMonitorUrl] = useState('');
  const [monitorInterval, setMonitorInterval] = useState(300);
  const [demoServices, setDemoServices] = useState<DemoService[]>([]);
  const [selectedDemoService, setSelectedDemoService] = useState('');
  const [monitorError, setMonitorError] = useState('');
  const [monitorNotice, setMonitorNotice] = useState('');
  const [dashboardLoading, setDashboardLoading] = useState(false);
  const [monitorBusy, setMonitorBusy] = useState(false);
  const [editingMonitor, setEditingMonitor] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [editUrl, setEditUrl] = useState('');
  const [editInterval, setEditInterval] = useState(300);
  const [checkHistory, setCheckHistory] = useState<Record<number, MonitorCheck[]>>({});
  const [githubStatus, setGithubStatus] = useState<GitHubStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    const sessionToken = localStorage.getItem('codepulse_session_token');

    async function loadCurrentUser() {
      try {
        const response = await fetch(`${apiUrl}/api/v1/auth/me`, {
          headers: sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {},
        });
        if (!response.ok) throw new Error(`Authentication check failed (${response.status}).`);
        const result: { authenticated?: boolean; user?: UserProfile | null } = await response.json();
        if (!cancelled && result.authenticated && result.user) {
          setUser(result.user);
        } else if (!cancelled) {
          localStorage.removeItem('codepulse_session_token');
        }
      } catch {
        if (!cancelled) setAuthError('Could not reach the CodePulse server. Make sure the backend is running, then try again.');
      } finally {
        if (!cancelled) setAuthChecked(true);
      }
    }

    void loadCurrentUser();
    return () => {
      cancelled = true;
    };
  }, [apiUrl]);

  useEffect(() => {
    if (!authChecked || user || !googleButtonElement) return;
    if (!googleClientId) {
      setAuthError('Google sign-in is not configured. Set VITE_GOOGLE_CLIENT_ID in frontend/.env.local and restart Vite.');
      return;
    }

    let cancelled = false;
    const renderButton = () => {
      if (cancelled || !window.google) return;

      window.google.accounts.id.initialize({
        client_id: googleClientId,
        callback: async ({ credential }) => {
          setAuthBusy(true);
          setAuthError('');
          setAuthNotice('');

          try {
            const response = await fetch(`${apiUrl}/api/v1/auth/google`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ credential }),
            });
            const result: { user?: UserProfile; session_token?: string; detail?: string } = await response.json();
            if (!response.ok || !result.user || !result.session_token) {
              throw new Error(result.detail ?? 'Google sign-in could not be completed.');
            }
            localStorage.setItem('codepulse_session_token', result.session_token);
            setUser(result.user);
          } catch (error) {
            setAuthError(error instanceof Error ? error.message : 'Google sign-in could not be completed.');
          } finally {
            setAuthBusy(false);
          }
        },
      });
      window.google.accounts.id.renderButton(googleButtonElement, {
        theme: 'filled_blue',
        size: 'large',
        text: 'continue_with',
        shape: 'rectangular',
        width: 320,
      });
    };

    const script = document.querySelector<HTMLScriptElement>('script[src="https://accounts.google.com/gsi/client"]');
    const handleScriptLoad = () => renderButton();
    const handleScriptError = () => {
      setAuthError('Google sign-in could not load. Check your internet connection and reload the page.');
    };

    if (window.google) {
      renderButton();
    } else if (script) {
      script.addEventListener('load', handleScriptLoad);
      script.addEventListener('error', handleScriptError);
    } else {
      setAuthError('Google sign-in could not load. Reload the page and try again.');
    }

    return () => {
      cancelled = true;
      script?.removeEventListener('load', handleScriptLoad);
      script?.removeEventListener('error', handleScriptError);
    };
  }, [apiUrl, authChecked, googleButtonElement, googleClientId, user]);

  useEffect(() => {
    if (!user) {
      setMonitors([]);
      setIncidents([]);
      return;
    }
    void loadDashboard();
  }, [user, apiUrl]);

  async function monitoringRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
    const sessionToken = localStorage.getItem('codepulse_session_token');
    const headers = new Headers(init.headers);
    headers.set('Authorization', `Bearer ${sessionToken ?? ''}`);
    if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const response = await fetch(`${apiUrl}/api/v1${path}`, { ...init, headers });
    const payload = response.status === 204 ? undefined : await response.json();
    if (!response.ok) {
      const detail = typeof payload?.detail === 'string' ? payload.detail : `Request failed (${response.status}).`;
      throw new Error(detail);
    }
    return payload as T;
  }

  async function loadDashboard() {
    setDashboardLoading(true);
    setMonitorError('');
    try {
      const [monitorResult, incidentResult, integrationStatus, demoServiceResult] = await Promise.all([
        monitoringRequest<{ items: Monitor[] }>('/monitors'),
        monitoringRequest<{ items: MonitorIncident[] }>('/monitoring/incidents'),
        monitoringRequest<GitHubStatus>('/monitoring/github-status'),
        monitoringRequest<{ items: DemoService[] }>('/monitoring/demo-services'),
      ]);
      setMonitors(monitorResult.items);
      setIncidents(incidentResult.items);
      setGithubStatus(integrationStatus);
      setDemoServices(demoServiceResult.items);
    } catch (error) {
      setMonitorError(error instanceof Error ? error.message : 'Could not load monitoring data.');
    } finally {
      setDashboardLoading(false);
    }
  }

  async function createMonitor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMonitorBusy(true);
    setMonitorError('');
    setMonitorNotice('');
    try {
      await monitoringRequest<Monitor>('/monitors', {
        method: 'POST',
        body: JSON.stringify({
          name: monitorName,
          url: selectedDemoService ? `demo://${selectedDemoService}` : monitorUrl,
          interval_seconds: monitorInterval,
        }),
      });
      setMonitorName('');
      setMonitorUrl('');
      setMonitorInterval(300);
      setSelectedDemoService('');
      setMonitorNotice('Monitor saved. Its first scheduled check will run shortly.');
      await loadDashboard();
    } catch (error) {
      setMonitorError(error instanceof Error ? error.message : 'Could not create the monitor.');
    } finally {
      setMonitorBusy(false);
    }
  }

  async function saveMonitor(monitorId: number) {
    setMonitorBusy(true);
    setMonitorError('');
    setMonitorNotice('');
    try {
      await monitoringRequest<Monitor>(`/monitors/${monitorId}`, {
        method: 'PATCH',
        body: JSON.stringify({ name: editName, url: editUrl, interval_seconds: editInterval }),
      });
      setEditingMonitor(null);
      setMonitorNotice('Monitor updated.');
      await loadDashboard();
    } catch (error) {
      setMonitorError(error instanceof Error ? error.message : 'Could not update the monitor.');
    } finally {
      setMonitorBusy(false);
    }
  }

  async function deleteMonitor(monitorId: number) {
    setMonitorBusy(true);
    setMonitorError('');
    try {
      await monitoringRequest<void>(`/monitors/${monitorId}`, { method: 'DELETE' });
      setMonitorNotice('Monitor and its history were deleted.');
      await loadDashboard();
    } catch (error) {
      setMonitorError(error instanceof Error ? error.message : 'Could not delete the monitor.');
    } finally {
      setMonitorBusy(false);
    }
  }

  async function runMonitorNow(monitorId: number) {
    setMonitorBusy(true);
    setMonitorError('');
    try {
      await monitoringRequest<MonitorCheck>(`/monitors/${monitorId}/check`, { method: 'POST' });
      setMonitorNotice('Check completed.');
      await loadDashboard();
    } catch (error) {
      setMonitorError(error instanceof Error ? error.message : 'The monitor check failed.');
    } finally {
      setMonitorBusy(false);
    }
  }

  async function loadCheckHistory(monitorId: number) {
    try {
      const result = await monitoringRequest<{ items: MonitorCheck[] }>(`/monitors/${monitorId}/checks`);
      setCheckHistory((current) => ({ ...current, [monitorId]: result.items }));
    } catch (error) {
      setMonitorError(error instanceof Error ? error.message : 'Could not load check history.');
    }
  }

  async function diagnoseIncident(incidentId: number) {
    setMonitorBusy(true);
    setMonitorError('');
    try {
      await monitoringRequest(`/monitoring/incidents/${incidentId}/diagnose`, { method: 'POST' });
      setMonitorNotice('Diagnosis saved. Check the provider status shown with the incident.');
      await loadDashboard();
    } catch (error) {
      setMonitorError(error instanceof Error ? error.message : 'Could not diagnose this incident.');
    } finally {
      setMonitorBusy(false);
    }
  }

  async function proposeIncidentPatch(incidentId: number) {
    setMonitorBusy(true);
    setMonitorError('');
    setMonitorNotice('');
    try {
      const result = await monitoringRequest<{ patch_proposal: PatchProposal }>(
        `/monitoring/incidents/${incidentId}/patch`,
        { method: 'POST' },
      );
      setMonitorNotice(result.patch_proposal.validation.passed
        ? 'Patch proposal passed isolated validation. Review its diff before requesting a draft PR.'
        : 'Patch proposal was saved, but validation failed. A draft PR is blocked.');
      await loadDashboard();
    } catch (error) {
      setMonitorError(error instanceof Error ? error.message : 'Could not generate and validate this patch.');
    } finally {
      setMonitorBusy(false);
    }
  }

  async function createIncidentDraftPr(incidentId: number) {
    setMonitorBusy(true);
    setMonitorError('');
    setMonitorNotice('');
    try {
      const result = await monitoringRequest<{
        github_result: NonNullable<PatchProposal['github_result']>;
      }>(`/monitoring/incidents/${incidentId}/draft-pr`, { method: 'POST' });
      const pr = result.github_result;
      setMonitorNotice(pr.status === 'created' && pr.url
        ? `Draft PR created for human review: ${pr.url}`
        : pr.note ?? 'GitHub integration is not configured; no PR was created.');
      await loadDashboard();
    } catch (error) {
      setMonitorError(error instanceof Error ? error.message : 'Draft PR creation failed.');
      await loadDashboard();
    } finally {
      setMonitorBusy(false);
    }
  }

  async function signOut() {
    try {
      const sessionToken = localStorage.getItem('codepulse_session_token');
      const response = await fetch(`${apiUrl}/api/v1/auth/logout`, {
        method: 'POST',
        headers: sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {},
      });
      if (!response.ok) throw new Error(`Sign-out failed (${response.status}).`);
      localStorage.removeItem('codepulse_session_token');
      setUser(null);
      setAuthNotice('You have been signed out.');
      setAuthError('');
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : 'Sign-out could not be completed.');
    }
  }

  if (!authChecked) {
    return (
      <main className="flex min-h-screen items-center justify-center text-sm text-slate-400" aria-live="polite">
        Checking your sign-in...
      </main>
    );
  }

  if (!user) {
    return (
      <main className="flex min-h-screen items-center justify-center px-5 py-12">
        <section className="w-full max-w-md rounded-3xl border border-slate-800 bg-slate-900/80 p-8 text-center shadow-2xl shadow-slate-950/50">
          <p className="text-xs uppercase tracking-[0.3em] text-cyan-400">Observability</p>
          <h1 className="mt-3 text-3xl font-bold text-white">CodePulse AI</h1>
          <p className="mt-3 text-sm text-slate-400">Sign in to open your monitoring dashboard.</p>
          <div className="mt-8 flex min-h-11 justify-center" ref={setGoogleButtonElement} />
          {authBusy && <p className="mt-4 text-sm text-slate-300" aria-live="polite">Signing you in...</p>}
          {authError && <p className="mt-5 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-left text-sm text-rose-200" role="alert">{authError}</p>}
          {authNotice && <p className="mt-5 text-sm text-emerald-300" role="status">{authNotice}</p>}
          <p className="mt-6 text-xs text-slate-500">New to CodePulse? Continue with Google to get started.</p>
          <nav className="mt-6 flex justify-center gap-5 text-xs text-slate-500" aria-label="Legal">
            <a className="hover:text-slate-300" href="/privacy.html">Privacy Policy</a>
            <a className="hover:text-slate-300" href="/terms.html">Terms of Service</a>
          </nav>
        </section>
      </main>
    );
  }

  async function checkWebsite() {
    setProbing(true);
    setProbeError('');
    setProbeResult(null);

    try {
      const response = await fetch(`${apiUrl}/api/v1/monitor/probe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: websiteUrl }),
      });
      const result: ProbeResult & { detail?: string } = await response.json();
      if (!response.ok) {
        throw new Error(typeof result.detail === 'string' ? result.detail : 'Please enter a valid public website URL.');
      }
      setProbeResult(result);
    } catch (error) {
      setProbeError(error instanceof Error ? error.message : 'The website check could not be completed.');
    } finally {
      setProbing(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto max-w-4xl p-6">
        <header className="mb-8 flex flex-col gap-4 border-b border-slate-800 pb-6 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-xs uppercase tracking-[0.3em] text-cyan-400">Observability</p>
            <h1 className="mt-2 text-3xl font-bold">CodePulse AI</h1>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="text-slate-400">{user.name || user.email}</span>
            <button
              type="button"
              onClick={() => void signOut()}
              className="rounded-full border border-slate-700 px-3 py-1 text-slate-300 hover:border-slate-500 hover:text-white"
              aria-label={`Sign out ${user.email}`}
            >
              Sign out
            </button>
          </div>
        </header>

        <main>
          <section className="mb-6 rounded-3xl border border-cyan-900/70 bg-slate-900/80 p-6 shadow-xl md:p-8">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.25em] text-cyan-400">Scheduled monitoring</p>
                <h2 className="mt-2 text-2xl font-semibold text-white">Your monitors</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
                  Add public HTTP(S) endpoints for recurring checks. Checks run while the backend is awake;
                  sleeping free hosting cannot guarantee continuous monitoring.
                </p>
              </div>
              <button type="button" onClick={() => void loadDashboard()} disabled={dashboardLoading || monitorBusy}
                className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:border-slate-500 disabled:opacity-60">
                {dashboardLoading ? 'Refreshing...' : 'Refresh'}
              </button>
            </div>

            {monitorError && <p className="mt-4 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200" role="alert">{monitorError}</p>}
            {monitorNotice && <p className="mt-4 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-200" role="status">{monitorNotice}</p>}

            <form onSubmit={(event) => void createMonitor(event)} className="mt-6 grid gap-3 md:grid-cols-[1fr_2fr_150px_auto]">
              <label className="sr-only" htmlFor="monitor-name">Monitor name</label>
              <input id="monitor-name" value={monitorName} onChange={(event) => setMonitorName(event.target.value)}
                placeholder="Monitor name" required maxLength={120}
                className="min-w-0 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-400" />
              <label className="sr-only" htmlFor="monitor-url">Public website URL</label>
              <input id="monitor-url" type="url" value={monitorUrl} onChange={(event) => setMonitorUrl(event.target.value)}
                placeholder={selectedDemoService ? 'Using included demo service' : 'https://example.com'} required={!selectedDemoService}
                disabled={Boolean(selectedDemoService)}
                onInput={() => setSelectedDemoService('')}
                className="min-w-0 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-500 focus:border-cyan-400 disabled:opacity-50" />
              <label className="sr-only" htmlFor="monitor-interval">Check interval in seconds</label>
              <input id="monitor-interval" type="number" min={60} max={86400} step={60} value={monitorInterval}
                onChange={(event) => setMonitorInterval(Number(event.target.value))} required
                className="rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white outline-none focus:border-cyan-400" />
              <button type="submit" disabled={monitorBusy}
                className="rounded-xl bg-cyan-500 px-5 py-3 text-sm font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-60">
                Add monitor
              </button>
              <div className="md:col-span-4">
                <label className="sr-only" htmlFor="demo-service">Or choose an included demo service</label>
                <select id="demo-service" value={selectedDemoService}
                  onChange={(event) => {
                    const serviceId = event.target.value;
                    setSelectedDemoService(serviceId);
                    setMonitorUrl('');
                    if (serviceId) {
                      const selected = demoServices.find((service) => service.id === serviceId);
                      if (selected) setMonitorName(selected.name);
                    }
                  }}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white outline-none focus:border-cyan-400">
                  <option value="">Or choose an included demo service</option>
                  {demoServices.map((service) => <option key={service.id} value={service.id}>{service.name} · Docker network</option>)}
                </select>
                <p className="mt-2 text-xs text-slate-500">Demo monitors reach only fixed internal service names; custom private or loopback URLs remain blocked.</p>
              </div>
            </form>
            <p className="mt-2 text-xs text-slate-500">Intervals: 60 seconds to 24 hours. Limit: 20 monitors per account.</p>

            {dashboardLoading && monitors.length === 0 ? (
              <p className="mt-6 text-sm text-slate-400" aria-live="polite">Loading your monitors...</p>
            ) : monitors.length === 0 ? (
              <p className="mt-6 rounded-xl border border-dashed border-slate-700 p-5 text-sm text-slate-400">
                No monitors yet. Add a public URL above to start scheduled checks.
              </p>
            ) : (
              <div className="mt-6 grid gap-4">
                {monitors.map((monitor) => (
                  <article key={monitor.id} className="rounded-2xl border border-slate-800 bg-slate-950/70 p-5">
                    {editingMonitor === monitor.id ? (
                      <div className="grid gap-3 md:grid-cols-[1fr_2fr_150px_auto_auto]">
                        <input aria-label="Edit monitor name" value={editName} onChange={(event) => setEditName(event.target.value)}
                          className="min-w-0 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
                        <input aria-label="Edit monitor URL or demo target" type="text" value={editUrl} onChange={(event) => setEditUrl(event.target.value)}
                          className="min-w-0 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
                        <input aria-label="Edit interval seconds" type="number" min={60} max={86400} step={60} value={editInterval}
                          onChange={(event) => setEditInterval(Number(event.target.value))}
                          className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white" />
                        <button type="button" onClick={() => void saveMonitor(monitor.id)} disabled={monitorBusy}
                          className="rounded-lg bg-cyan-500 px-3 py-2 text-sm font-semibold text-slate-950">Save</button>
                        <button type="button" onClick={() => setEditingMonitor(null)}
                          className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300">Cancel</button>
                      </div>
                    ) : (
                      <>
                        <div className="flex flex-wrap items-start justify-between gap-4">
                          <div className="min-w-0">
                            <h3 className="text-lg font-semibold text-white">{monitor.name}</h3>
                            <p className="mt-1 break-all text-sm text-slate-400">{monitor.url}</p>
                            <p className="mt-2 text-xs text-slate-500">
                              Every {monitor.interval_seconds}s · {monitor.enabled ? 'Enabled' : 'Paused'}
                            </p>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <button type="button" onClick={() => void runMonitorNow(monitor.id)} disabled={monitorBusy}
                              className="rounded-lg border border-cyan-700 px-3 py-2 text-xs text-cyan-200 disabled:opacity-60">Check now</button>
                            <button type="button" onClick={() => {
                              setEditingMonitor(monitor.id);
                              setEditName(monitor.name);
                              setEditUrl(monitor.url);
                              setEditInterval(monitor.interval_seconds);
                            }} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300">Edit</button>
                            <button type="button" onClick={() => void monitoringRequest(`/monitors/${monitor.id}`, {
                              method: 'PATCH', body: JSON.stringify({ enabled: !monitor.enabled }),
                            }).then(() => loadDashboard()).catch((error: unknown) => setMonitorError(error instanceof Error ? error.message : 'Could not change monitor state.'))}
                              disabled={monitorBusy} className="rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300">
                              {monitor.enabled ? 'Pause' : 'Resume'}
                            </button>
                            <button type="button" onClick={() => void deleteMonitor(monitor.id)} disabled={monitorBusy}
                              className="rounded-lg border border-rose-900 px-3 py-2 text-xs text-rose-300">Delete</button>
                          </div>
                        </div>
                        <div className="mt-4 rounded-xl border border-slate-800 p-4">
                          <p className="text-xs uppercase tracking-wide text-slate-500">Latest check</p>
                          {monitor.latest_check ? (
                            <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
                              <span className={monitor.latest_check.result === 'healthy' ? 'text-emerald-300' : 'text-amber-300'}>
                                {monitor.latest_check.result} {monitor.latest_check.status_code ? `(${monitor.latest_check.status_code})` : ''}
                              </span>
                              <span className="text-slate-300">{monitor.latest_check.response_time_ms} ms</span>
                              <span className="text-slate-500">{new Date(monitor.latest_check.checked_at).toLocaleString()}</span>
                            </div>
                          ) : <p className="mt-2 text-sm text-slate-400">Waiting for the first scheduled check.</p>}
                        </div>
                        <button type="button" onClick={() => void loadCheckHistory(monitor.id)}
                          className="mt-3 text-sm text-cyan-300 hover:text-cyan-200">Load check history</button>
                        {checkHistory[monitor.id] && (
                          <ul className="mt-3 grid gap-2 border-t border-slate-800 pt-3">
                            {checkHistory[monitor.id].map((check) => (
                              <li key={check.id} className="flex flex-wrap justify-between gap-2 text-xs text-slate-400">
                                <span>{new Date(check.checked_at).toLocaleString()} · {check.result}</span>
                                <span>{check.status_code ?? 'No HTTP response'} · {check.response_time_ms} ms</span>
                              </li>
                            ))}
                          </ul>
                        )}
                      </>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="mb-6 rounded-3xl border border-slate-800 bg-slate-900/80 p-6 md:p-8">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.25em] text-cyan-400">Incident response</p>
                <h2 className="mt-2 text-2xl font-semibold text-white">Monitor incidents</h2>
              </div>
              <span className="text-xs text-slate-500">
                GitHub: {githubStatus?.configured
                  ? `configured for ${githubStatus.repository} (${githubStatus.base_branch})`
                  : 'mock / not configured'}
              </span>
            </div>
            {incidents.length === 0 ? (
              <p className="mt-5 text-sm text-slate-400">No incidents detected. A 5xx response, repeated failures, or a check taking at least 5 seconds opens an incident.</p>
            ) : (
              <div className="mt-5 grid gap-4">
                {incidents.map((incident) => (
                  <article key={incident.id} className="rounded-2xl border border-slate-800 bg-slate-950/70 p-5">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div>
                        <h3 className="font-semibold text-white">{incident.title}</h3>
                        <p className="mt-1 text-xs text-slate-400">{incident.severity} · {incident.status} · {new Date(incident.created_at).toLocaleString()}</p>
                      </div>
                      {!incident.diagnosis && incident.status === 'open' && (
                        <button type="button" onClick={() => void diagnoseIncident(incident.id)} disabled={monitorBusy}
                          className="rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 disabled:opacity-60">Diagnose</button>
                      )}
                    </div>
                    <pre className="mt-4 overflow-x-auto rounded-xl bg-slate-900 p-3 text-xs text-slate-300">{JSON.stringify(incident.evidence, null, 2)}</pre>
                    {incident.diagnosis && (
                      <div className="mt-4 rounded-xl border border-cyan-900/70 p-4">
                        <p className="text-xs uppercase tracking-wide text-cyan-300">Diagnosis · {incident.diagnosis_provider}</p>
                        <p className="mt-2 text-sm text-slate-200">{String(incident.diagnosis.recommended_action ?? incident.diagnosis.recommended_fix ?? 'No recommendation returned.')}</p>
                        <pre className="mt-3 overflow-x-auto text-xs text-slate-400">{JSON.stringify(incident.diagnosis, null, 2)}</pre>
                        {!incident.patch_proposal && incident.status === 'open' && (
                          <button type="button" onClick={() => void proposeIncidentPatch(incident.id)} disabled={monitorBusy}
                            className="mt-3 rounded-lg border border-cyan-700 px-4 py-2 text-sm text-cyan-200 disabled:opacity-60">
                            {monitorBusy ? 'Validating...' : 'Propose and validate demo patch'}
                          </button>
                        )}
                      </div>
                    )}
                    {incident.patch_proposal && (
                      <div className="mt-4 rounded-xl border border-violet-900/70 p-4">
                        <p className="text-xs uppercase tracking-wide text-violet-300">
                          Patch validation · {incident.patch_proposal.validation_status}
                        </p>
                        <p className="mt-2 text-sm text-slate-200">{incident.patch_proposal.summary}</p>
                        <p className="mt-1 text-xs text-slate-400">Target: {incident.patch_proposal.file_path}</p>
                        <p className="mt-3 text-sm text-slate-300">{incident.patch_proposal.validation.summary}</p>
                        <dl className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
                          {Object.entries(incident.patch_proposal.validation.details).map(([check, result]) => (
                            <div key={check} className="flex justify-between gap-2 rounded bg-slate-900 px-3 py-2">
                              <dt className="text-slate-400">{check.replace(/_/g, ' ')}</dt>
                              <dd className={result === 'passed' ? 'text-emerald-300' : result === 'failed' || result === 'timed_out' ? 'text-rose-300' : 'text-slate-500'}>{result}</dd>
                            </div>
                          ))}
                        </dl>
                        <details className="mt-3">
                          <summary className="cursor-pointer text-sm text-cyan-300">Review proposed diff and risks</summary>
                          <pre className="mt-3 overflow-x-auto rounded-xl bg-slate-950 p-3 text-xs text-slate-300">{incident.patch_proposal.diff}</pre>
                          <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-amber-200">
                            {incident.patch_proposal.risks.map((risk) => <li key={risk}>{risk}</li>)}
                          </ul>
                        </details>
                        {incident.patch_proposal.validation_status === 'passed'
                          && !incident.patch_proposal.github_result?.status.includes('created') && (
                            <div className="mt-4">
                              <button type="button" onClick={() => void createIncidentDraftPr(incident.id)}
                                disabled={monitorBusy || !githubStatus?.configured}
                                className="rounded-lg bg-violet-500 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50">
                                {monitorBusy ? 'Creating draft...' : 'Create draft PR'}
                              </button>
                              {!githubStatus?.configured && (
                                <p className="mt-2 text-xs text-slate-400">
                                  Configure a least-privilege server-side GitHub token, owner, repository, and base branch to enable real PR creation. No mock URL is shown as a real PR.
                                </p>
                              )}
                            </div>
                          )}
                        {incident.patch_proposal.github_result && (
                          <div className="mt-4 rounded-lg border border-slate-700 p-3 text-sm">
                            <p className="text-slate-300">
                              Draft PR status: {incident.patch_proposal.github_result.status} ({incident.patch_proposal.github_result.source})
                            </p>
                            {incident.patch_proposal.github_result.url && (
                              <a className="mt-1 inline-block text-cyan-300 underline" href={incident.patch_proposal.github_result.url} target="_blank" rel="noreferrer">
                                Open draft PR {incident.patch_proposal.github_result.number ? `#${incident.patch_proposal.github_result.number}` : ''}
                              </a>
                            )}
                            {incident.patch_proposal.github_result.error && (
                              <p className="mt-1 text-rose-300">{incident.patch_proposal.github_result.error}</p>
                            )}
                            {incident.patch_proposal.github_result.note && (
                              <p className="mt-1 text-amber-200">{incident.patch_proposal.github_result.note}</p>
                            )}
                          </div>
                        )}
                      </div>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="rounded-3xl border border-slate-800 bg-slate-900/80 p-6 shadow-2xl shadow-slate-950/30 md:p-9">
            <p className="text-xs uppercase tracking-[0.25em] text-cyan-400">Website health check</p>
            <h2 className="mt-3 text-2xl font-semibold text-white md:text-3xl">Which website should we monitor?</h2>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
              Paste its public URL. We will request that address and show the observed HTTP status and response time.
            </p>
            <form onSubmit={(event) => { event.preventDefault(); void checkWebsite(); }} className="mt-7 flex flex-col gap-3 sm:flex-row">
              <label className="sr-only" htmlFor="website-url">Website URL</label>
              <input
                id="website-url"
                type="text"
                inputMode="url"
                autoComplete="url"
                placeholder="https://example.com"
                value={websiteUrl}
                onChange={(event) => setWebsiteUrl(event.target.value)}
                required
                className="min-w-0 flex-1 rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none placeholder:text-slate-500 focus:border-cyan-400"
              />
              <button
                type="submit"
                disabled={probing}
                className="rounded-xl bg-cyan-500 px-6 py-3 font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:cursor-wait disabled:opacity-60"
              >
                {probing ? 'Checking...' : 'Check website'}
              </button>
            </form>
            {probeError && <p className="mt-4 text-sm text-rose-300" role="alert">{probeError}</p>}
          </section>

          {probeResult && (
            <section className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/80 p-6" aria-live="polite">
              <div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
                <div className="min-w-0">
                  <p className="text-xs uppercase tracking-[0.2em] text-slate-500">Observed result</p>
                  <h3 className={`mt-2 text-2xl font-bold ${
                    probeResult.result === 'healthy'
                      ? 'text-emerald-300'
                      : probeResult.result === 'unavailable' || probeResult.result === 'server_error'
                        ? 'text-rose-300'
                        : 'text-amber-300'
                  }`}>
                    {probeResult.result === 'healthy' ? 'Responding successfully' :
                      probeResult.result === 'unavailable' ? 'Not reachable' :
                        probeResult.result === 'server_error' ? 'Server error' :
                          probeResult.result === 'client_error' ? 'Client error response' : 'Redirect response'}
                  </h3>
                  <p className="mt-2 break-all text-sm text-slate-300">{probeResult.url}</p>
                </div>
                <button
                  type="button"
                  onClick={() => void checkWebsite()}
                  disabled={probing}
                  className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-200 hover:border-slate-500 disabled:opacity-60"
                >
                  Check again
                </button>
              </div>
              <p className="mt-4 text-sm text-slate-300">{probeResult.message}</p>
              <div className="mt-5 grid gap-3 sm:grid-cols-3">
                <ProbeFact label="HTTP status" value={probeResult.status_code === null ? 'No response' : String(probeResult.status_code)} />
                <ProbeFact label="Response time" value={`${probeResult.response_time_ms} ms`} />
                <ProbeFact label="Reachable" value={probeResult.reachable ? 'Yes' : 'No'} />
              </div>
              <p className="mt-4 text-xs leading-5 text-slate-500">
                This is a single HTTP check of the URL you entered. It does not inspect the site’s database or other internal services.
                Checked {new Date(probeResult.checked_at).toLocaleString()}.
              </p>
            </section>
          )}
        </main>
      </div>
    </div>
  );
}

function ProbeFact({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4">
      <p className="text-xs uppercase tracking-[0.15em] text-slate-500">{label}</p>
      <p className="mt-2 text-lg font-semibold text-slate-100">{value}</p>
    </div>
  );
}
