/**
 * Public application form. LANE 1.
 *
 * The only candidate-facing page before the interview. No account, no login —
 * an email address and a PDF.
 *
 * The consent checkbox is not decoration. Processing a resume without recorded
 * consent is the violation, so the form blocks submission rather than
 * collecting first and asking later.
 */

import { useState } from "react";
import { useParams } from "react-router-dom";

import { Card } from "../../components/intake/primitives";
import { api } from "../../lib/api";

type Submitted = { application_id: string };

export default function ApplicationForm() {
  const { jobId = "" } = useParams();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Submitted | null>(null);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setBusy(true);

    const form = new FormData(e.currentTarget);
    form.set("job_id", jobId);

    try {
      setDone(await api.postForm<Submitted>("/intake/applications", form));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <main className="wrap narrow">
        <Card className="mt-10 bg-lime">
          <h1>Application received</h1>
          <p className="m-0">
            Thanks. We're reviewing your application now. If you're a match
            you'll get an email with a link to a short screening interview -
            usually within a day.
          </p>
        </Card>
      </main>
    );
  }

  return (
    <main className="wrap narrow">
      <h1 className="mt-6">Apply</h1>
      <p className="hint mb-5">
        Résumé screening, then a short AI interview if you're a match.
      </p>

      <Card>
        <form onSubmit={onSubmit} className="grid gap-3.5">
          <label>
            Email
            <input
              className="nb-input"
              name="email"
              type="email"
              required
              autoComplete="email"
            />
          </label>

          <label>
            Full name
            <input
              className="nb-input"
              name="full_name"
              type="text"
              autoComplete="name"
            />
          </label>

          <label>
            Phone <span className="hint">optional</span>
            <input
              className="nb-input"
              name="phone"
              type="tel"
              autoComplete="tel"
            />
          </label>

          <label>
            Résumé <span className="hint">PDF, up to 10MB</span>
            <input
              className="nb-input file:mr-3 file:rounded-full file:border-2 file:border-ink file:bg-lavender file:px-3 file:py-1 file:font-semibold"
              name="resume"
              type="file"
              accept="application/pdf"
              required
            />
          </label>

          {/* Wording matters here - this is the disclosure, not a formality. */}
          <label className="flex items-start gap-2.5 rounded-xl border-2 border-ink bg-paper p-3 text-sm font-normal">
            <input
              name="consent"
              type="checkbox"
              value="true"
              required
              className="mt-1 size-4 shrink-0 accent-black"
            />
            <span>
              I agree that my résumé may be processed by AI to assess my
              application, and that if I'm invited to interview it will be
              conducted by an AI interviewer and recorded. A human reviews every
              outcome. I can request deletion of my data at any time.
            </span>
          </label>

          {error && (
            <p role="alert" className="error m-0">
              {error}
            </p>
          )}

          <button
            type="submit"
            className="nb-btn nb-btn-primary justify-self-start"
            disabled={busy}
          >
            {busy ? "Submitting..." : "Submit application"}
          </button>
        </form>
      </Card>
    </main>
  );
}
