/**
 * Recruiter review queue. LANE 1.
 *
 * Where the human-in-the-loop requirement physically lives. Applications the
 * model marked `review` land here, and so does anything a recruiter wants to
 * override.
 *
 * Deliberately shows the model's evidence next to its recommendation. A
 * recommendation without the quotes behind it invites rubber-stamping, which
 * is the failure mode the review step exists to prevent.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { api } from "../../lib/api";

type Screening = {
  outcome: "accept" | "reject" | "review";
  confidence: number;
  rationale: string;
  evidence: string[];
  concerns: string[];
};

type HardCheck = { check: string; passed: boolean; detail: string };

type Application = {
  id: string;
  status: string;
  parsed_resume: { full_name?: string; email?: string } | null;
  hard_checks: HardCheck[];
  screening: Screening | null;
  screening_model_id: string | null;
  screening_prompt_version: string | null;
};

/** Mirrors ApplicationStatus in shared/models/candidate.py. */
const FILTERS = [
  { value: "review", label: "Needs review" },
  { value: "rejected_screen", label: "Rejected at screening" },
  { value: "invited", label: "Invited, not started" },
  { value: "interviewing", label: "Interviewing now" },
  { value: "scored", label: "Scored" },
  { value: "rejected_post", label: "Rejected after interview" },
  { value: "advanced", label: "Advanced" },
  { value: "failed", label: "Failed — needs a retry" },
] as const;

export default function ReviewQueue() {
  const { jobId = "" } = useParams();
  const [status, setStatus] = useState("review");
  const qc = useQueryClient();

  const { data, isLoading } = useQuery({
    queryKey: ["applications", jobId, status],
    queryFn: () =>
      api.get<Application[]>(
        `/intake/applications?job_id=${jobId}&status_filter=${status}`,
      ),
  });

  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: "accept" | "reject" }) =>
      api.post(`/intake/applications/${id}/decide`, { decision }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["applications", jobId] }),
  });

  if (isLoading) return <main className="wrap">Loading…</main>;

  return (
    <main className="wrap">
      <h1>Review queue</h1>

      <select value={status} onChange={(e) => setStatus(e.target.value)}>
        {FILTERS.map((f) => (
          <option key={f.value} value={f.value}>
            {f.label}
          </option>
        ))}
      </select>

      {status === "rejected_screen" && (
        <p className="hint">
          Rejected by the hard requirements, before any interview. Worth
          scanning — if a requirement was extracted wrongly it shows up here as
          a pile of good candidates. Inviting one from here overrides the filter.
        </p>
      )}

      {data?.length === 0 && <p>Nothing here.</p>}

      {data?.map((app) => (
        <article key={app.id} className="card">
          <header>
            <strong>{app.parsed_resume?.full_name ?? "Unnamed candidate"}</strong>
            <span className="hint">{app.parsed_resume?.email}</span>
          </header>

          {app.screening && (
            <>
              <p>
                <b>{app.screening.outcome}</b>{" "}
                <span className="hint">
                  confidence {(app.screening.confidence * 100).toFixed(0)}%
                </span>
              </p>
              <p>{app.screening.rationale}</p>

              {app.screening.evidence.length > 0 && (
                <details open>
                  <summary>Evidence</summary>
                  <ul>
                    {app.screening.evidence.map((e, i) => (
                      <li key={i}>{e}</li>
                    ))}
                  </ul>
                </details>
              )}

              {app.screening.concerns.length > 0 && (
                <details>
                  <summary>Concerns</summary>
                  <ul>
                    {app.screening.concerns.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </details>
              )}

              {/* Which model and prompt produced this. Two decisions made under
                  different versions are not directly comparable. */}
              <p className="hint">
                {app.screening_model_id} · prompt {app.screening_prompt_version}
              </p>
            </>
          )}

          <details>
            <summary>Hard checks</summary>
            <ul>
              {app.hard_checks.map((c, i) => (
                <li key={i}>
                  {c.passed ? "pass" : "FAIL"} — {c.check}: {c.detail}
                </li>
              ))}
            </ul>
          </details>

          <footer>
            <button
              onClick={() => decide.mutate({ id: app.id, decision: "accept" })}
              disabled={decide.isPending}
            >
              Invite to interview
            </button>
            <button
              onClick={() => decide.mutate({ id: app.id, decision: "reject" })}
              disabled={decide.isPending}
            >
              Reject
            </button>
          </footer>
        </article>
      ))}
    </main>
  );
}
