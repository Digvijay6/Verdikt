export type Recommendation = "advance" | "hold" | "reject";

export type JobSummary = {
  id: string;
  title: string;
  seniority: string;
  status: "draft" | "open" | "closed" | "archived";
  rubric_version: string;
};

export type LeaderboardEntry = {
  application_id: string;
  interview_id: string;
  candidate_name: string;
  score: number;
  overall: number;
  composite_score: number | null;
  technical_accuracy_score: number | null;
  project_depth_score: number | null;
  followup_resilience_score: number | null;
  consistency_score: number | null;
  percentile: number | null;
  recommendation: Recommendation;
  integrity_score: number;
  flagged: boolean;
  review_reasons: string[];
};

export type RubricEvidence = {
  quote: string;
  rationale: string;
};

export type FixedRubricAssessment = {
  question_type: string;
  technical_accuracy_score: number | null;
  technical_accuracy_evidence: RubricEvidence | null;
  project_depth_score: number | null;
  project_depth_evidence: RubricEvidence | null;
  ownership_level: string | null;
  ownership_evidence: RubricEvidence | null;
  followup_resilience_score: number | null;
  followup_resilience_evidence: RubricEvidence | null;
  consistency_label: string;
  consistency_evidence: RubricEvidence;
  central_to_role: boolean;
  resume_headline_claim: boolean;
  flagship_project: boolean;
};

export type DimensionScore = {
  key: string;
  score: number;
  evidence: string;
  rationale: string;
};

export type AnswerScore = {
  question_id: string;
  dimensions: DimensionScore[];
  weighted_score: number;
  fixed_rubric: FixedRubricAssessment;
  followed_up: boolean;
  model_id: string;
  prompt_version: string;
};

export type IntegrityEvent = {
  type: string;
  severity: number;
  at_ms: number;
  detail: Record<string, unknown>;
};

export type InterviewResult = {
  interview_id: string;
  org_id: string;
  application_id: string;
  job_id: string;
  answers: AnswerScore[];
  holistic: {
    score: number;
    strengths: string[];
    concerns: string[];
    representative_quote: string;
    model_id: string;
    prompt_version: string;
  };
  role_fit: number;
  seniority: string | null;
  technical_accuracy_score: number | null;
  project_depth_score: number | null;
  followup_resilience_score: number | null;
  consistency_score: number | null;
  composite_score: number | null;
  needs_human_review: boolean;
  review_reasons: string[];
  overall: number;
  percentile: number | null;
  recommendation: Recommendation;
  hard_gate_applied: boolean;
  integrity: {
    score: number;
    events: IntegrityEvent[];
    summary: string;
  };
  rubric_version: string;
  scored_at: string;
};

export type RecruiterChatMessage = {
  role: "user" | "assistant";
  content: string;
  created_at: string;
  model_id: string | null;
  prompt_version: string | null;
};

export type RecruiterChatSession = {
  session_id: string | null;
  interview_id: string;
  messages: RecruiterChatMessage[];
};
