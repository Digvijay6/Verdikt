/** Create the company.  LANE 1
 *
 * Reached when someone is signed in but belongs to no organization — which is
 * the normal state immediately after signup, not an error.
 */

import { useState } from "react";
import { Navigate } from "react-router-dom";

import { api, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";

/** "Acme Corp" -> "acme-corp". Suggested, not enforced. */
function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
}

export default function Onboarding() {
  const { session, org, refreshOrg } = useAuth();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!session) return <Navigate to="/login" replace />;
  if (org) return <Navigate to="/jobs" replace />;

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await api.post("/auth/organizations", { name: name.trim(), slug });
      await refreshOrg();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? "That name is already taken. Try another."
          : err instanceof Error
            ? err.message
            : "Could not create the company.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="wrap narrow">
      <h1>Set up your company</h1>
      <p className="hint">
        Everything you create — jobs, candidates, interviews — belongs to this
        company and is visible only to people you invite.
      </p>

      <form onSubmit={onSubmit} className="nb-card">
        <label>
          Company name
          <input
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              if (!slugEdited) setSlug(slugify(e.target.value));
            }}
            required
            minLength={2}
            autoFocus
          />
        </label>

        <label>
          Identifier <span className="hint">lowercase, used in links</span>
          <input
            value={slug}
            onChange={(e) => {
              setSlugEdited(true);
              setSlug(slugify(e.target.value));
            }}
            required
            minLength={2}
            pattern="[a-z0-9]+(-[a-z0-9]+)*"
          />
        </label>

        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}

        <button className="nb-btn nb-btn-primary" type="submit" disabled={busy || !name.trim() || !slug}>
          {busy ? "Creating..." : "Create company"}
        </button>
      </form>
    </main>
  );
}
