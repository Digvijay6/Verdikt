import type { ReactNode } from "react";

import type { Recommendation } from "./types";

export function formatLabel(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function formatScore(value: number | null, suffix = "") {
  return value === null ? "N/A" : `${Math.round(value)}${suffix}`;
}

export function ScoreBar({
  label,
  value,
  note,
}: {
  label: string;
  value: number | null;
  note?: ReactNode;
}) {
  const bounded = value === null ? 0 : Math.max(0, Math.min(100, value));
  const tone =
    value === null
      ? "score-meter-na"
      : bounded >= 75
        ? "score-meter-good"
        : bounded >= 50
          ? "score-meter-mid"
          : "score-meter-low";

  return (
    <div className="score-metric">
      <div className="score-metric-head">
        <span>{label}</span>
        <strong>{formatScore(value)}</strong>
      </div>
      <div
        className={`score-meter ${tone}`}
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value ?? undefined}
        aria-valuetext={value === null ? "Not applicable" : `${Math.round(value)} out of 100`}
      >
        <span style={{ width: `${bounded}%` }} />
      </div>
      {note && <div className="score-metric-note">{note}</div>}
    </div>
  );
}

export function StatusBadge({
  children,
  tone = "plain",
}: {
  children: ReactNode;
  tone?: "plain" | "good" | "cool" | "review" | "danger";
}) {
  return <span className={`insight-badge insight-badge-${tone}`}>{children}</span>;
}

export function RecommendationBadge({ value }: { value: Recommendation }) {
  const tone = value === "advance" ? "good" : value === "reject" ? "danger" : "cool";
  return <StatusBadge tone={tone}>{formatLabel(value)}</StatusBadge>;
}

export function reviewReasonLabel(reason: string) {
  const labels: Record<string, string> = {
    inflated_central_claim: "Inflated central claim",
    weak_headline_followup: "Weak headline follow-up",
    unclear_flagship_ownership: "Unclear flagship ownership",
    background_heavy_high_score: "Background-heavy high score",
    must_have_hard_gate: "Must-have requirement not demonstrated",
    integrity_flag: "Integrity signals need review",
    rejection_requires_human_review: "Rejection needs human decision",
  };
  return labels[reason] ?? formatLabel(reason);
}

export function readableError(error: unknown) {
  if (!(error instanceof Error)) return "The request could not be completed.";
  try {
    const parsed = JSON.parse(error.message) as { detail?: string };
    return parsed.detail ?? error.message;
  } catch {
    return error.message;
  }
}
