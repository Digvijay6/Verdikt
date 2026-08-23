import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  formatScore,
  readableError,
  RecommendationBadge,
  StatusBadge,
} from "../../components/insights/ScoreDisplay";
import type {
  JobSummary,
  LeaderboardEntry,
} from "../../components/insights/types";
import "../../components/insights/insights.css";
import { api } from "../../lib/api";

type ReviewFilter = "all" | "review" | "clear";

function median(values: number[]) {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? Math.round((sorted[middle - 1] + sorted[middle]) / 2)
    : sorted[middle];
}

export default function LeaderboardPage() {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("all");

  const jobsQuery = useQuery({
    queryKey: ["jobs"],
    queryFn: () => api.get<JobSummary[]>("/intake/jobs"),
  });

  const selectedJobId = jobId ?? jobsQuery.data?.[0]?.id;
  const selectedJob = jobsQuery.data?.find((job) => job.id === selectedJobId);

  const leaderboardQuery = useQuery({
    queryKey: ["insights-leaderboard", selectedJobId],
    queryFn: () =>
      api.get<LeaderboardEntry[]>(
        `/insights/leaderboard?job_id=${encodeURIComponent(selectedJobId!)}`,
      ),
    enabled: Boolean(selectedJobId),
    refetchInterval: 15_000,
  });

  const visibleEntries = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return (leaderboardQuery.data ?? []).filter((entry) => {
      const matchesName =
        normalized.length === 0 || entry.candidate_name.toLowerCase().includes(normalized);
      const matchesReview =
        reviewFilter === "all" ||
        (reviewFilter === "review" && entry.flagged) ||
        (reviewFilter === "clear" && !entry.flagged);
      return matchesName && matchesReview;
    });
  }, [leaderboardQuery.data, query, reviewFilter]);

  const entries = leaderboardQuery.data ?? [];
  const advanced = entries.filter((entry) => entry.recommendation === "advance").length;
  const flagged = entries.filter((entry) => entry.flagged).length;

  return (
    <main className="wrap insights-page">
      <header className="insights-page-head">
        <div>
          <p className="insights-eyebrow">Interview performance</p>
          <h1>Leaderboard</h1>
          <p className="hint m-0">
            Ranked within one job and one scoring version. Review evidence before deciding.
          </p>
        </div>
        <label className="job-picker">
          <span>Job</span>
          <select
            className="nb-input"
            value={selectedJobId ?? ""}
            disabled={!jobsQuery.data?.length}
            onChange={(event) => navigate(`/leaderboard/${event.target.value}`)}
          >
            {!jobsQuery.data?.length && <option value="">No jobs available</option>}
            {jobsQuery.data?.map((job) => (
              <option key={job.id} value={job.id}>
                {job.title} ({job.seniority})
              </option>
            ))}
          </select>
        </label>
      </header>

      {jobsQuery.isError && (
        <div className="insights-message insights-message-error" role="alert">
          <strong>Jobs could not be loaded.</strong>
          <span>{readableError(jobsQuery.error)}</span>
        </div>
      )}

      {!jobsQuery.isPending && jobsQuery.data?.length === 0 && (
        <section className="insights-empty">
          <h2>Create a job first</h2>
          <p>Leaderboards are job-specific so candidates are compared against the same rubric.</p>
          <Link className="nb-btn nb-btn-primary" to="/jobs">
            Go to jobs
          </Link>
        </section>
      )}

      {selectedJobId && (
        <>
          <section className="leaderboard-summary" aria-label="Leaderboard summary">
            <div>
              <span>Scored candidates</span>
              <strong>{entries.length}</strong>
            </div>
            <div>
              <span>Median score</span>
              <strong>{entries.length ? median(entries.map((entry) => entry.score)) : "-"}</strong>
            </div>
            <div>
              <span>Advance</span>
              <strong>{advanced}</strong>
            </div>
            <div className={flagged > 0 ? "summary-review" : ""}>
              <span>Needs review</span>
              <strong>{flagged}</strong>
            </div>
          </section>

          <section className="leaderboard-section">
            <div className="leaderboard-toolbar">
              <div>
                <h2>{selectedJob?.title ?? "Selected job"}</h2>
                <p className="hint m-0">
                  {selectedJob ? `${selectedJob.seniority} - ${selectedJob.rubric_version}` : "Loading job..."}
                </p>
              </div>
              <label className="candidate-search">
                <span className="sr-only">Search candidates</span>
                <input
                  className="nb-input"
                  type="search"
                  value={query}
                  placeholder="Search candidate"
                  onChange={(event) => setQuery(event.target.value)}
                />
              </label>
              <div className="insight-segmented" aria-label="Review status filter">
                {(["all", "review", "clear"] as const).map((filter) => (
                  <button
                    key={filter}
                    type="button"
                    aria-pressed={reviewFilter === filter}
                    onClick={() => setReviewFilter(filter)}
                  >
                    {filter === "all" ? "All" : filter === "review" ? "Needs review" : "Clear"}
                  </button>
                ))}
              </div>
            </div>

            {leaderboardQuery.isPending && (
              <div className="insights-loading" aria-live="polite">
                Loading scored interviews...
              </div>
            )}

            {leaderboardQuery.isError && (
              <div className="insights-message insights-message-error" role="alert">
                <strong>Leaderboard could not be loaded.</strong>
                <span>{readableError(leaderboardQuery.error)}</span>
                <button className="nb-btn" onClick={() => void leaderboardQuery.refetch()}>
                  Retry
                </button>
              </div>
            )}

            {!leaderboardQuery.isPending && !leaderboardQuery.isError && entries.length === 0 && (
              <div className="insights-empty insights-empty-quiet">
                <h2>No scored interviews yet</h2>
                <p>Candidates appear here after post-call scoring finishes.</p>
              </div>
            )}

            {entries.length > 0 && visibleEntries.length === 0 && (
              <div className="insights-empty insights-empty-quiet">
                <h2>No matching candidates</h2>
                <p>Change the search or review filter to see more results.</p>
              </div>
            )}

            {visibleEntries.length > 0 && (
              <div className="leaderboard-table-wrap">
                <table className="leaderboard-table">
                  <thead>
                    <tr>
                      <th scope="col">Rank</th>
                      <th scope="col">Candidate</th>
                      <th scope="col">Score</th>
                      <th scope="col">Technical</th>
                      <th scope="col">Depth</th>
                      <th scope="col">Follow-up</th>
                      <th scope="col">Consistency</th>
                      <th scope="col">Percentile</th>
                      <th scope="col">Recommendation</th>
                      <th scope="col">Review</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleEntries.map((entry) => {
                      const absoluteRank = entries.findIndex(
                        (candidate) => candidate.interview_id === entry.interview_id,
                      ) + 1;
                      return (
                        <tr key={entry.interview_id}>
                          <td data-label="Rank">
                            <span className={`rank-mark rank-${Math.min(absoluteRank, 4)}`}>
                              {absoluteRank}
                            </span>
                          </td>
                          <td data-label="Candidate" className="candidate-cell">
                            <Link
                              to={`/leaderboard/${selectedJobId}/candidates/${entry.interview_id}`}
                              state={{ candidateName: entry.candidate_name, jobId: selectedJobId }}
                            >
                              {entry.candidate_name}
                            </Link>
                            <span>{entry.review_reasons.length} review signal{entry.review_reasons.length === 1 ? "" : "s"}</span>
                          </td>
                          <td data-label="Score">
                            <strong className="leader-score">{entry.score}</strong>
                          </td>
                          <td data-label="Technical">{formatScore(entry.technical_accuracy_score)}</td>
                          <td data-label="Depth">{formatScore(entry.project_depth_score)}</td>
                          <td data-label="Follow-up">{formatScore(entry.followup_resilience_score)}</td>
                          <td data-label="Consistency">{formatScore(entry.consistency_score)}</td>
                          <td data-label="Percentile">
                            {entry.percentile === null ? "N/A" : `${Math.round(entry.percentile)}th`}
                          </td>
                          <td data-label="Recommendation">
                            <RecommendationBadge value={entry.recommendation} />
                          </td>
                          <td data-label="Review">
                            {entry.flagged ? (
                              <StatusBadge tone="review">Review</StatusBadge>
                            ) : (
                              <StatusBadge>Clear</StatusBadge>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}
