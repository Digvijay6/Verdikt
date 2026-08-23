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

import { Card, Pill, SectionHead, StatTile } from "../../components/intake/primitives";
import { RubricViewer, type Rubric } from "../../components/intake/RubricViewer";
import { Tabs } from "../../components/intake/Tabs";
import { api } from "../../lib/api";

type Job = {
  id: string;
  title: string;
  seniority: string;
  // Named for the question bank it used to build. It now tracks the rubric
  // build; the column keeps its name because migrations are additive only.
  question_bank_status: "pending" | "building" | "ready" | "failed";
  question_bank_error: string | null;
  rubric: Rubric | null;
  rubric_version: string;
};

type Stats = {
  total: number;
  processing: number;
  needs_review: number;
  rejected_screen: number;
  rejected_post: number;
  interview_remaining: number;
  interview_ongoing: number;
  scored: number;
  advanced: number;
  failed: number;
};

/**
 * The pipeline at a glance. One grouped query behind it, not one per tile.
 *
 * `needs_review` and `failed` are surfaced separately because they are the two
 * that need a person: the first is the compliance queue, the second is stuck
 * work that would otherwise sit invisible.
 */
function JobStats({ jobId }: { jobId: string }) {
  const { data } = useQuery({
    queryKey: ["job-stats", jobId],
    queryFn: () => api.get<Stats>(`/intake/jobs/${jobId}/stats`),
    // Applications arrive and move through the pipeline on their own.
    refetchInterval: 10_000,
  });

  if (!data || data.total === 0) {
    return <p className="hint">No applications yet.</p>;
  }

  type Tone = "plain" | "good" | "cool" | "attention";
  const tiles: Array<[string, number, Tone]> = [
    ["Applications", data.total, "plain"],
    ["Processing", data.processing, "plain"],
    ["Needs review", data.needs_review, data.needs_review > 0 ? "attention" : "plain"],
    ["Rejected", data.rejected_screen + data.rejected_post, "plain"],
    ["Interview pending", data.interview_remaining, "plain"],
    ["Interviewing now", data.interview_ongoing, data.interview_ongoing > 0 ? "cool" : "plain"],
    ["Scored", data.scored, data.scored > 0 ? "good" : "plain"],
    ["Advanced", data.advanced, data.advanced > 0 ? "good" : "plain"],
    ["Failed", data.failed, data.failed > 0 ? "attention" : "plain"],
  ];

  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(7.5rem,1fr))] gap-2.5">
      {tiles.map(([label, value, tone]) => (
        <StatTile key={label} value={value} label={label} tone={tone} />
      ))}
    </div>
  );
}

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
      <div className="mb-6 flex flex-wrap items-end gap-4">
        <div className="mr-auto">
          <h1>Jobs</h1>
          <p className="hint m-0">
            Every job carries one scoring rubric. Questions are written per
            candidate against it.
          </p>
        </div>
        <button
          className={open ? "nb-btn" : "nb-btn nb-btn-primary"}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "Cancel" : "New job"}
        </button>
      </div>

      {open && (
        <Card className="mb-6">
          <SectionHead
            title="New job"
            sub="Gemini extracts the rubric from the description once this is saved."
          />
          <form onSubmit={onCreate} className="grid gap-3.5 sm:grid-cols-2">
            <label className="sm:col-span-1">
              Title
              <input className="nb-input" name="title" required />
            </label>
            <label className="sm:col-span-1">
              Seniority
              <input
                className="nb-input"
                name="seniority"
                placeholder="e.g. senior"
                required
              />
            </label>
            <label className="sm:col-span-2">
              Job description
              <textarea className="nb-input" name="jd_text" rows={9} required />
            </label>
            <label>
              Minimum years <span className="hint">optional</span>
              <input
                className="nb-input"
                name="min_years"
                type="number"
                step="0.5"
                min="0"
              />
            </label>
            <label>
              Required skills{" "}
              <span className="hint">comma separated - a hard gate</span>
              <input className="nb-input" name="required_skills" />
            </label>
            <label className="sm:col-span-2">
              Preferred skills{" "}
              <span className="hint">comma separated - never gates alone</span>
              <input className="nb-input" name="preferred_skills" />
            </label>
            <label className="flex items-center gap-2.5 font-normal sm:col-span-2">
              <input
                name="remote_ok"
                type="checkbox"
                defaultChecked
                className="size-4 accent-black"
              />
              <span>Remote acceptable</span>
            </label>
            <div className="sm:col-span-2">
              <button
                type="submit"
                className="nb-btn nb-btn-primary"
                disabled={create.isPending}
              >
                {create.isPending ? "Creating..." : "Create job"}
              </button>
            </div>
          </form>
        </Card>
      )}

      <div className="space-y-6">
        {jobs?.map((job) => (
          <JobCard
            key={job.id}
            job={job}
            onRebuild={() => rebuild.mutate(job.id)}
          />
        ))}
      </div>
    </main>
  );
}

/** One job: its pipeline, and the rubric every candidate for it is scored on. */
function JobCard({ job, onRebuild }: { job: Job; onRebuild: () => void }) {
  const [tab, setTab] = useState("pipeline");
  const building = job.question_bank_status === "building";

  const statusTone =
    job.question_bank_status === "ready"
      ? "good"
      : job.question_bank_status === "failed"
        ? "attention"
        : "cool";

  return (
    <article>
      <div className="mb-3 flex flex-wrap items-center gap-2.5 px-1">
        <strong className="text-lg font-extrabold">{job.title}</strong>
        <Pill>{job.seniority}</Pill>
        <Pill tone={statusTone}>
          {building ? "building rubric..." : job.question_bank_status}
        </Pill>
        {job.rubric && <Pill tone="cool">{job.rubric_version}</Pill>}

        <span className="ml-auto flex flex-wrap items-center gap-2">
          <Link className="nb-btn" to={`/applications/${job.id}`}>
            Review queue
          </Link>
          <Link className="nb-btn" to={`/apply/${job.id}`}>
            Application link
          </Link>
          <button className="nb-btn" onClick={onRebuild} disabled={building}>
            Rebuild rubric
          </button>
        </span>
      </div>

      {job.question_bank_error && (
        <p role="alert" className="error mb-2 px-1">
          {job.question_bank_error}
        </p>
      )}

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "pipeline", label: "Pipeline" },
          {
            id: "rubric",
            label: "Rubric",
            badge: job.rubric?.competencies.length,
          },
        ]}
      >
        {tab === "pipeline" ? (
          <JobStats jobId={job.id} />
        ) : job.rubric ? (
          <RubricViewer rubric={job.rubric} />
        ) : (
          <p className="hint m-0">
            {building
              ? "Building. This takes a couple of minutes - there is a validation loop."
              : "No rubric yet. Rebuild to generate one."}
          </p>
        )}
      </Tabs>
    </article>
  );
}
