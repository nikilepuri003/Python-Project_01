import { useEffect, useState } from 'react';

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

export default function App() {
  const apiUrl = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000';
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

  useEffect(() => {
    let cancelled = false;

    async function loadCurrentUser() {
      try {
        const response = await fetch(`${apiUrl}/api/v1/auth/me`);
        if (!response.ok) throw new Error(`Authentication check failed (${response.status}).`);
        const result: { authenticated?: boolean; user?: UserProfile | null } = await response.json();
        if (!cancelled && result.authenticated && result.user) setUser(result.user);
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
            const result: { user?: UserProfile; detail?: string } = await response.json();
            if (!response.ok || !result.user) {
              throw new Error(result.detail ?? 'Google sign-in could not be completed.');
            }
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

  async function signOut() {
    try {
      const response = await fetch(`${apiUrl}/api/v1/auth/logout`, { method: 'POST' });
      if (!response.ok) throw new Error(`Sign-out failed (${response.status}).`);
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
