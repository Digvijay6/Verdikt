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

import { Card, Pill } from "../../components/intake/primitives";
import { api } from "../../lib/api";

type Question = {
  id: string;
  order: number;
  type: "technical" | "behavioral" | "situational" | "poison";
  prompt: string;
  competency: string;
  must_have: boolean;
  follow_up_guidance?: string | null;
};

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

  // Written for this candidate from the job's rubric plus their resume (D35).
  questions: Question[] | null;
  questions_model_id: string | null;
  questions_rubric_version: string | null;
  // Generation failed and the invite went out anyway. Surfaced because
  // otherwise a recruiter has no way to know the interview will run on the
  // job-wide fallback rather than questions about this person's own work.
  questions_error: string | null;
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

  if (isLoading) return <main className="wrap">Loading...</main>;

  return (
    <main className="wrap">
      <div className="mb-6 flex flex-wrap items-end gap-4">
        <div className="mr-auto">
          <h1>Review queue</h1>
          <p className="hint m-0">
            Every rejection is reviewed by a person. That is the promise
            compliance.md makes.
          </p>
        </div>
        <label className="m-0">
          <span className="hint">Showing</span>
          <select
            className="nb-input"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            {FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {status === "rejected_screen" && (
        <Card className="mb-6 bg-lavender">
          <p className="m-0 text-sm">
            Rejected by the hard requirements, before any interview. Worth
            scanning - if a requirement was extracted wrongly it shows up here
            as a pile of good candidates. Inviting one from here overrides the
            filter.
          </p>
        </Card>
      )}

      {data?.length === 0 && (
        <Card>
          <p className="m-0">Nothing here.</p>
        </Card>
      )}

      <div className="space-y-5">
        {data?.map((app) => (
          <Card key={app.id}>
            <header className="mb-3 flex flex-wrap items-center gap-2.5">
              <strong className="text-lg font-semibold">
                {app.parsed_resume?.full_name ?? "Unnamed candidate"}
              </strong>
              <span className="hint">{app.parsed_resume?.email}</span>
              {app.screening && (
                <Pill
                  tone={
                    app.screening.outcome === "accept"
                      ? "good"
                      : app.screening.outcome === "reject"
                        ? "attention"
                        : "cool"
                  }
                >
                  {app.screening.outcome} ·{" "}
                  {(app.screening.confidence * 100).toFixed(0)}%
                </Pill>
              )}
            </header>

            {app.screening && (
              <>
                <p className="mt-0">{app.screening.rationale}</p>

                {app.screening.evidence.length > 0 && (
                  <details open className="mb-2">
                    <summary className="cursor-pointer font-bold">
                      Evidence
                    </summary>
                    <ul className="mt-1.5 space-y-1 pl-5">
                      {app.screening.evidence.map((e, i) => (
                        <li key={i}>{e}</li>
                      ))}
                    </ul>
                  </details>
                )}

                {app.screening.concerns.length > 0 && (
                  <details className="mb-2">
                    <summary className="cursor-pointer font-bold">
                      Concerns
                    </summary>
                    <ul className="mt-1.5 space-y-1 pl-5">
                      {app.screening.concerns.map((c, i) => (
                        <li key={i}>{c}</li>
                      ))}
                    </ul>
                  </details>
                )}
              </>
            )}

            <details className="mb-2">
              <summary className="cursor-pointer font-bold">
                Hard checks
              </summary>
              <ul className="mt-1.5 space-y-1 pl-5">
                {app.hard_checks.map((c, i) => (
                  <li key={i}>
                    <b>{c.passed ? "pass" : "FAIL"}</b> - {c.check}: {c.detail}
                  </li>
                ))}
              </ul>
            </details>

            <CandidateQuestions app={app} />

            {/* Which model and prompt produced this. Two decisions made under
                different versions are not directly comparable. */}
            <p className="hint mt-3 mb-3 font-mono text-xs">
              {app.screening_model_id} · prompt {app.screening_prompt_version}
            </p>

            <footer className="flex flex-wrap gap-2.5">
              <button
                className="nb-btn nb-btn-primary"
                onClick={() => decide.mutate({ id: app.id, decision: "accept" })}
                disabled={decide.isPending}
              >
                Invite to interview
              </button>
              <button
                className="nb-btn nb-btn-danger"
                onClick={() => decide.mutate({ id: app.id, decision: "reject" })}
                disabled={decide.isPending}
              >
                Reject
              </button>
            </footer>
          </Card>
        ))}
      </div>
    </main>
  );
}

/**
 * The questions this specific candidate will be asked.
 *
 * Worth showing even though nobody can review every set: it is how a recruiter
 * checks that a probe actually reached what this person built, and it is the
 * only place `questions_error` becomes visible. An interview silently running
 * on fallback questions looks identical to a good one until the transcript
 * arrives.
 */
function CandidateQuestions({ app }: { app: Application }) {
  if (app.questions_error) {
    return (
      <p role="alert" className="error my-2">
        Question generation failed - this interview will fall back to the
        job-wide set. {app.questions_error}
      </p>
    );
  }
  if (!app.questions?.length) return null;

  return (
    <details className="mb-2">
      <summary className="cursor-pointer font-bold">
        Interview questions
        <span className="hint"> · {app.questions.length} for this candidate</span>
      </summary>

      <ol className="mt-2 list-none space-y-2 p-0">
        {app.questions.map((q) => (
          <li
            key={q.id}
            className="nb-row bg-paper"
          >
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <b className="tabular-nums">{q.order}</b>
              <Pill tone={q.type === "poison" ? "attention" : "plain"}>
                {q.competency}
              </Pill>
              {q.must_have && <Pill tone="cool">must-have</Pill>}
            </div>
            <p className="m-0">{q.prompt}</p>
            {q.follow_up_guidance && (
              <p className="hint mt-1 mb-0">{q.follow_up_guidance}</p>
            )}
          </li>
        ))}
      </ol>

      <p className="hint mt-2 font-mono text-xs">
        {app.questions_model_id} · scored against rubric{" "}
        {app.questions_rubric_version}
      </p>
    </details>
  );
}
