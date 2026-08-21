/**
 * Job creation and list. LANE 1.
 *
 * Creating a job kicks off the ADK question_builder workflow in the
 * background, so the job appears immediately as `building` and this page polls
 * until the bank is ready. The build involves a validation loop that can take a
 * few revisions, so it is not instant.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api } from "../../lib/api";

type Job = {
  id: string;
  title: string;
  seniority: string;
  question_bank_status: "pending" | "building" | "ready" | "failed";
  question_bank_error: string | null;
  question_bank: unknown[] | null;
  rubric_version: string;
};

export default function JobsPage() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);

  const { data: jobs } = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api.get<Job[]>("/intake/jobs"),
    // Poll while anything is still building its question bank.
    refetchInterval: (q) =>
      q.state.data?.some((j) => j.question_bank_status === "building")
        ? 3000
        : false,
  });

  const create = useMutation({
    mutationFn: (body: unknown) => api.post<Job>("/intake/jobs", body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["jobs"] });
      setOpen(false);
    },
  });

  const rebuild = useMutation({
    mutationFn: (id: string) => api.post(`/intake/jobs/${id}/rebuild-questions`, {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });

  function onCreate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const list = (name: string) =>
      String(f.get(name) ?? "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);

    create.mutate({
      title: f.get("title"),
      seniority: f.get("seniority"),
      jd_text: f.get("jd_text"),
      screening_profile: {
        min_years_experience: f.get("min_years")
          ? Number(f.get("min_years"))
          : null,
        required_skills: list("required_skills"),
        preferred_skills: list("preferred_skills"),
        remote_ok: f.get("remote_ok") === "on",
      },
    });
  }

  return (
    <main className="wrap">
      <h1>Jobs</h1>
      <button onClick={() => setOpen((v) => !v)}>
        {open ? "Cancel" : "New job"}
      </button>

      {open && (
        <form onSubmit={onCreate} className="card">
          <label>
            Title
            <input name="title" required />
          </label>
          <label>
            Seniority
            <input name="seniority" placeholder="e.g. senior" required />
          </label>
          <label>
            Job description
            <textarea name="jd_text" rows={10} required />
          </label>
          <label>
            Minimum years <span className="hint">optional</span>
            <input name="min_years" type="number" step="0.5" min="0" />
          </label>
          <label>
            Required skills <span className="hint">comma separated — this is a hard gate</span>
            <input name="required_skills" />
          </label>
          <label>
            Preferred skills <span className="hint">comma separated — never gates alone</span>
            <input name="preferred_skills" />
          </label>
          <label className="consent">
            <input name="remote_ok" type="checkbox" defaultChecked />
            <span>Remote acceptable</span>
          </label>
          <button type="submit" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create job"}
          </button>
        </form>
      )}

      {jobs?.map((job) => (
        <article key={job.id} className="card">
          <header>
            <strong>{job.title}</strong>
            <span className="hint">{job.seniority}</span>
          </header>

          <p>
            Question bank: <b>{job.question_bank_status}</b>
            {job.question_bank_status === "ready" && (
              <span className="hint">
                {" "}
                · {job.question_bank?.length ?? 0} questions · {job.rubric_version}
              </span>
            )}
          </p>

          {job.question_bank_error && (
            <p role="alert" className="error">{job.question_bank_error}</p>
          )}

          <footer>
            <Link to={`/applications/${job.id}`}>Review queue</Link>
            <Link to={`/apply/${job.id}`}>Application link</Link>
            <button
              onClick={() => rebuild.mutate(job.id)}
              disabled={job.question_bank_status === "building"}
            >
              Rebuild questions
            </button>
          </footer>
        </article>
      ))}
    </main>
  );
}
