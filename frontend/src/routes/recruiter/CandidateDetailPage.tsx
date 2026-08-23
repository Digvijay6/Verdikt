import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Link, useLocation, useParams } from "react-router-dom";
import remarkGfm from "remark-gfm";

import {
  formatLabel,
  formatScore,
  readableError,
  RecommendationBadge,
  reviewReasonLabel,
  ScoreBar,
  StatusBadge,
} from "../../components/insights/ScoreDisplay";
import type {
  AnswerScore,
  InterviewResult,
  LeaderboardEntry,
  RecruiterChatSession,
  RubricEvidence,
} from "../../components/insights/types";
import { api } from "../../lib/api";

type LocationState = { candidateName?: string; jobId?: string } | null;

export default function CandidateDetailPage() {
  const { interviewId, jobId: routeJobId } = useParams();
  const location = useLocation();
  const state = location.state as LocationState;

  const interviewQuery = useQuery({
    queryKey: ["insights-interview", interviewId],
    queryFn: () => api.get<InterviewResult>(`/insights/interviews/${interviewId}`),
    enabled: Boolean(interviewId),
  });

  const jobId = interviewQuery.data?.job_id ?? routeJobId ?? state?.jobId;
  const leaderboardQuery = useQuery({
    queryKey: ["insights-leaderboard", jobId],
    queryFn: () =>
      api.get<LeaderboardEntry[]>(
        `/insights/leaderboard?job_id=${encodeURIComponent(jobId!)}`,
      ),
    enabled: Boolean(jobId),
  });

  const result = interviewQuery.data;
  const leaderboardEntry = leaderboardQuery.data?.find(
    (entry) => entry.interview_id === interviewId,
  );
  const candidateName = state?.candidateName ?? leaderboardEntry?.candidate_name ?? "Candidate";

  if (interviewQuery.isPending) {
    return (
      <main className="wrap insights-page">
        <div className="insights-loading" aria-live="polite">Loading interview evidence...</div>
      </main>
    );
  }

  if (interviewQuery.isError || !result) {
    return (
      <main className="wrap insights-page">
        <Link className="insights-back" to={jobId ? `/leaderboard/${jobId}` : "/leaderboard"}>
          Back to leaderboard
        </Link>
        <div className="insights-message insights-message-error" role="alert">
          <strong>Candidate score could not be loaded.</strong>
          <span>{readableError(interviewQuery.error)}</span>
          <button className="nb-btn" onClick={() => void interviewQuery.refetch()}>Retry</button>
        </div>
      </main>
    );
  }

  const score = result.composite_score ?? Math.round(((result.overall - 1) / 4) * 100);
  const percentile = result.percentile ?? leaderboardEntry?.percentile;
  const reviewReasons = [...result.review_reasons];
  if (result.integrity.score >= 60) reviewReasons.push("integrity_flag");
  if (result.hard_gate_applied) reviewReasons.push("must_have_hard_gate");
  if (result.recommendation === "reject") reviewReasons.push("rejection_requires_human_review");
  const uniqueReviewReasons = [...new Set(reviewReasons)];
  const needsReview = result.needs_human_review || uniqueReviewReasons.length > 0;

  return (
    <main className="wrap insights-page candidate-detail">
      <Link className="insights-back" to={`/leaderboard/${result.job_id}`}>
        Back to leaderboard
      </Link>

      <header className="candidate-hero">
        <div className="candidate-identity">
          <p className="insights-eyebrow">Scored interview</p>
          <h1>{candidateName}</h1>
          <div className="candidate-meta">
            <RecommendationBadge value={result.recommendation} />
            <StatusBadge tone={needsReview ? "review" : "plain"}>
              {needsReview ? "Human review needed" : "No review flags"}
            </StatusBadge>
            <span>{result.seniority ? formatLabel(result.seniority) : "Unspecified seniority"}</span>
          </div>
        </div>
        <div className="candidate-score-block">
          <span>Composite score</span>
          <strong>{Math.round(score)}</strong>
          <small>
            {percentile === null || percentile === undefined
              ? "Percentile pending"
              : `${Math.round(percentile)}th percentile in this job`}
          </small>
        </div>
      </header>

      <section className="candidate-score-band" aria-label="Score dimensions">
        <ScoreBar label="Technical accuracy" value={result.technical_accuracy_score} />
        <ScoreBar label="Project depth" value={result.project_depth_score} />
        <ScoreBar label="Follow-up resilience" value={result.followup_resilience_score} />
        <ScoreBar label="Consistency" value={result.consistency_score} />
      </section>

      <section className="candidate-section review-section">
        <div className="candidate-section-head">
          <div>
            <p className="insights-eyebrow">Decision support</p>
            <h2>Review signals</h2>
          </div>
          <StatusBadge tone={result.integrity.score >= 60 ? "review" : "plain"}>
            Integrity {result.integrity.score}/100
          </StatusBadge>
        </div>
        {uniqueReviewReasons.length > 0 ? (
          <ul className="review-reason-list">
            {uniqueReviewReasons.map((reason) => (
              <li key={reason}>{reviewReasonLabel(reason)}</li>
            ))}
          </ul>
        ) : (
          <p className="hint">No deterministic scoring or integrity rule triggered review.</p>
        )}
        <p className="integrity-summary">{result.integrity.summary}</p>
        <p className="human-review-note">
          Integrity signals are evidence for a recruiter. They do not change the score or make an automatic rejection.
        </p>
        {result.integrity.events.length > 0 && (
          <details className="integrity-events">
            <summary>{result.integrity.events.length} integrity event{result.integrity.events.length === 1 ? "" : "s"}</summary>
            <div>
              {result.integrity.events.map((event, index) => (
                <div className="integrity-event" key={`${event.type}-${event.at_ms}-${index}`}>
                  <strong>{formatLabel(event.type)}</strong>
                  <span>{Math.round(event.severity * 100)}% severity at {formatTime(event.at_ms)}</span>
                </div>
              ))}
            </div>
          </details>
        )}
      </section>

      <RecruiterChatPanel
        candidateName={candidateName}
        interviewId={result.interview_id}
      />

      <section className="candidate-section">
        <div className="candidate-section-head">
          <div>
            <p className="insights-eyebrow">Across the interview</p>
            <h2>Holistic assessment</h2>
          </div>
          <span className="legacy-score">{result.holistic.score.toFixed(1)}/5</span>
        </div>
        <blockquote className="representative-quote">{result.holistic.representative_quote}</blockquote>
        <div className="holistic-columns">
          <InsightList title="Strengths" items={result.holistic.strengths} tone="good" />
          <InsightList title="Concerns" items={result.holistic.concerns} tone="review" />
        </div>
      </section>

      <section className="candidate-section answer-section">
        <div className="candidate-section-head">
          <div>
            <p className="insights-eyebrow">Question-level scoring</p>
            <h2>Answer evidence</h2>
          </div>
          <span className="answer-count">{result.answers.length} answers</span>
        </div>
        <div className="answer-list">
          {result.answers.map((answer, index) => (
            <AnswerAssessment key={`${answer.question_id}-${index}`} answer={answer} index={index} />
          ))}
        </div>
      </section>

      <footer className="score-provenance">
        <div>
          <span>Rubric</span>
          <strong>{result.rubric_version}</strong>
        </div>
        <div>
          <span>Scored</span>
          <strong>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(result.scored_at))}</strong>
        </div>
        <div>
          <span>Interview ID</span>
          <strong>{result.interview_id}</strong>
        </div>
      </footer>
    </main>
  );
}

const starterQuestions = [
  "Why did this candidate receive this composite score?",
  "What is the strongest evidence in this interview?",
  "Which concern needs the most human review?",
];

function RecruiterChatPanel({
  candidateName,
  interviewId,
}: {
  candidateName: string;
  interviewId: string;
}) {
  const [message, setMessage] = useState("");
  const queryClient = useQueryClient();
  const queryKey = ["recruiter-chat", interviewId] as const;
  const chatQuery = useQuery({
    queryKey,
    queryFn: () =>
      api.get<RecruiterChatSession>(`/insights/interviews/${interviewId}/chat`),
  });
  const sendMessage = useMutation({
    mutationFn: (content: string) =>
      api.post<RecruiterChatSession>(`/insights/interviews/${interviewId}/chat`, {
        message: content,
      }),
    onSuccess: (session) => {
      queryClient.setQueryData(queryKey, session);
      setMessage("");
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const content = message.trim();
    if (content && !sendMessage.isPending) sendMessage.mutate(content);
  };

  const messages = chatQuery.data?.messages ?? [];
  return (
    <section className="candidate-section recruiter-chat-section">
      <div className="candidate-section-head">
        <div>
          <p className="insights-eyebrow">Grounded in interview evidence</p>
          <h2>Ask about {candidateName}</h2>
        </div>
        <StatusBadge tone="cool">Gemini score assistant</StatusBadge>
      </div>

      {chatQuery.isError ? (
        <div className="insights-message insights-message-error" role="alert">
          <strong>Chat history could not be loaded.</strong>
          <span>{readableError(chatQuery.error)}</span>
          <button className="nb-btn" onClick={() => void chatQuery.refetch()}>Retry</button>
        </div>
      ) : (
        <div className="recruiter-chat-log" aria-live="polite" aria-busy={sendMessage.isPending}>
          {chatQuery.isPending ? (
            <p className="chat-status">Loading conversation...</p>
          ) : messages.length === 0 ? (
            <div className="chat-starters">
              {starterQuestions.map((question) => (
                <button
                  key={question}
                  type="button"
                  onClick={() => setMessage(question)}
                >
                  {question}
                </button>
              ))}
            </div>
          ) : (
            messages.map((item, index) => (
              <article
                className={`chat-message chat-message-${item.role}`}
                key={`${item.created_at}-${item.role}-${index}`}
              >
                <strong>{item.role === "assistant" ? "Verdikt" : "You"}</strong>
                {item.role === "assistant" ? (
                  <div className="chat-markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
                      {item.content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <p>{item.content}</p>
                )}
                {item.role === "assistant" && item.model_id && (
                  <small>{item.model_id} - prompt {item.prompt_version}</small>
                )}
              </article>
            ))
          )}
          {sendMessage.isPending && <p className="chat-status">Reviewing the evidence...</p>}
        </div>
      )}

      {sendMessage.isError && (
        <div className="insights-message insights-message-error" role="alert">
          <strong>The score assistant could not answer.</strong>
          <span>{readableError(sendMessage.error)}</span>
        </div>
      )}

      <form className="recruiter-chat-form" onSubmit={submit}>
        <textarea
          aria-label="Question for the score assistant"
          maxLength={2000}
          onChange={(event) => setMessage(event.target.value)}
          placeholder="Ask about a score, answer, claim, or review flag"
          rows={3}
          value={message}
        />
        <button
          className="nb-btn nb-btn-primary"
          disabled={!message.trim() || sendMessage.isPending || chatQuery.isError}
          type="submit"
        >
          {sendMessage.isPending ? "Reviewing" : "Send"}
        </button>
      </form>
    </section>
  );
}

function InsightList({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "good" | "review";
}) {
  return (
    <div className={`insight-list insight-list-${tone}`}>
      <h3>{title}</h3>
      {items.length ? (
        <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
      ) : (
        <p className="hint">None recorded.</p>
      )}
    </div>
  );
}

function AnswerAssessment({ answer, index }: { answer: AnswerScore; index: number }) {
  const rubric = answer.fixed_rubric;
  const contexts = [
    rubric.central_to_role && "Central to role",
    rubric.resume_headline_claim && "Resume headline claim",
    rubric.flagship_project && "Flagship project",
    answer.followed_up && "Followed up",
  ].filter(Boolean) as string[];

  return (
    <details className="answer-card" open={index === 0}>
      <summary>
        <span className="answer-index">{String(index + 1).padStart(2, "0")}</span>
        <span className="answer-title">
          <strong>{formatLabel(rubric.question_type)} question</strong>
          <small>{answer.question_id}</small>
        </span>
        <span className="answer-score">{answer.weighted_score.toFixed(1)}/5</span>
      </summary>
      <div className="answer-body">
        {contexts.length > 0 && (
          <div className="answer-contexts">
            {contexts.map((context) => <StatusBadge key={context} tone="cool">{context}</StatusBadge>)}
          </div>
        )}
        <div className="answer-rubric-grid">
          <RubricMeasure label="Technical accuracy" score={rubric.technical_accuracy_score} evidence={rubric.technical_accuracy_evidence} />
          <RubricMeasure label="Project depth" score={rubric.project_depth_score} evidence={rubric.project_depth_evidence} />
          <RubricMeasure label="Follow-up resilience" score={rubric.followup_resilience_score} evidence={rubric.followup_resilience_evidence} />
          <RubricMeasure label="Ownership" value={rubric.ownership_level ? formatLabel(rubric.ownership_level) : null} evidence={rubric.ownership_evidence} />
          <RubricMeasure label="Consistency" value={formatLabel(rubric.consistency_label)} evidence={rubric.consistency_evidence} />
        </div>
        {answer.dimensions.length > 0 && (
          <details className="job-rubric-details">
            <summary>Role-specific rubric dimensions</summary>
            {answer.dimensions.map((dimension) => (
              <div className="job-dimension" key={dimension.key}>
                <div>
                  <strong>{formatLabel(dimension.key)}</strong>
                  <span>{dimension.score}/5</span>
                </div>
                <blockquote>{dimension.evidence}</blockquote>
                <p>{dimension.rationale}</p>
              </div>
            ))}
          </details>
        )}
        <p className="answer-provenance">{answer.model_id} - prompt {answer.prompt_version}</p>
      </div>
    </details>
  );
}

function RubricMeasure({
  label,
  score,
  value,
  evidence,
}: {
  label: string;
  score?: number | null;
  value?: string | null;
  evidence: RubricEvidence | null;
}) {
  const displayValue = value ?? (score === undefined ? "N/A" : formatScore(score));
  return (
    <article className={`rubric-measure ${evidence ? "" : "rubric-measure-na"}`}>
      <div className="rubric-measure-head">
        <h3>{label}</h3>
        <strong>{displayValue}</strong>
      </div>
      {evidence ? (
        <>
          <blockquote>{evidence.quote}</blockquote>
          <p>{evidence.rationale}</p>
        </>
      ) : (
        <p>Not measured by this question.</p>
      )}
    </article>
  );
}

function formatTime(milliseconds: number) {
  const seconds = Math.floor(milliseconds / 1000);
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}
