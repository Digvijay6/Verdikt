/** Account creation.  LANE 1
 *
 * Creates the person, not the company. The organization is a separate step,
 * because a Supabase project with email confirmation on returns no session
 * here — so there is nobody to attribute an organization to yet.
 */

import { useState } from "react";
import { Link, Navigate } from "react-router-dom";

import { useAuth } from "../../lib/auth";

export default function Signup() {
  const { session, signUp } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkInbox, setCheckInbox] = useState(false);

  // With confirmation off, signUp returns a session and this lands them
  // straight on onboarding.
  if (session) return <Navigate to="/onboarding" replace />;

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const form = new FormData(e.currentTarget);
    try {
      const { needsEmailConfirm } = await signUp(
        String(form.get("email")),
        String(form.get("password")),
      );
      if (needsEmailConfirm) setCheckInbox(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the account.");
    } finally {
      setBusy(false);
    }
  }

  if (checkInbox) {
    return (
      <main className="wrap narrow">
        <h1>Check your email</h1>
        <p>
          We've sent you a confirmation link. Open it, then come back and{" "}
          <Link to="/login">sign in</Link> to set up your company.
        </p>
      </main>
    );
  }

  return (
    <main className="wrap narrow">
      <h1>Create an account</h1>

      <form onSubmit={onSubmit} className="nb-card">
        <label>
          Work email
          <input className="nb-input" name="email" type="email" required autoComplete="email" autoFocus />
        </label>
        <label>
          Password <span className="hint">at least 8 characters</span>
          <input className="nb-input"
            name="password"
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
          />
        </label>

        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}

        <button className="nb-btn nb-btn-primary" type="submit" disabled={busy}>
          {busy ? "Creating..." : "Create account"}
        </button>
      </form>

      <p className="hint">
        Already have one? <Link to="/login">Sign in</Link>.
      </p>
    </main>
  );
}
