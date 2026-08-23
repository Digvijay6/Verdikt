/** Recruiter sign-in.  LANE 1 */

import { useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";

import { useAuth } from "../../lib/auth";

export default function Login() {
  const { session, signIn } = useAuth();
  const location = useLocation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (session) {
    const to = (location.state as { from?: string } | null)?.from ?? "/jobs";
    return <Navigate to={to} replace />;
  }

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const form = new FormData(e.currentTarget);
    try {
      await signIn(String(form.get("email")), String(form.get("password")));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="wrap narrow">
      <h1>Sign in</h1>

      <form onSubmit={onSubmit} className="nb-card">
        <label>
          Work email
          <input className="nb-input" name="email" type="email" required autoComplete="email" autoFocus />
        </label>
        <label>
          Password
          <input className="nb-input"
            name="password"
            type="password"
            required
            autoComplete="current-password"
          />
        </label>

        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}

        <button className="nb-btn nb-btn-primary" type="submit" disabled={busy}>
          {busy ? "Signing in..." : "Sign in"}
        </button>
      </form>

      <p className="hint">
        No account yet? <Link to="/signup">Create one</Link>.
      </p>
    </main>
  );
}
