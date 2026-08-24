"""Seed ten complete rubric-v2 interview results for leaderboard testing.

Run from backend/ so Settings loads backend/.env:

    python -m scripts.seed_scoring_examples --dry-run
    python -m scripts.seed_scoring_examples

Idempotent: fixed demo ids are upserted, so rerunning refreshes the examples.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from shared.db import db
from shared.interview_scoring import apply_rubric_to_result, build_interview_score_row
from shared.models.interview import IntegrityReport
from shared.models.scoring import (
    AnswerScore,
    ConsistencyLabel,
    DimensionScore,
    FixedRubricAssessment,
    HolisticScore,
    InterviewResult,
    OwnershipLevel,
    Recommendation,
    RubricEvidence,
    ScoringQuestionType,
)

ORG_SLUG = "acme"
ORG_NAME = "Acme Corp"
JOB_ID = "10000000-0000-4000-8000-000000000001"
DEMO_NAMESPACE = UUID("fcb31571-ef4d-48cc-9c83-e8bf3d3a4037")
SCORED_AT = datetime(2026, 8, 23, 9, 0, tzinfo=UTC)

QUESTION_BANK = [
    {
        "id": "q-background-01",
        "order": 1,
        "type": "behavioral",
        "prompt": "Tell me about the backend project that best represents your experience.",
        "competency": "Relevant experience",
        "dimensions": [],
        "must_have": False,
    },
    {
        "id": "q-technical-01",
        "order": 2,
        "type": "technical",
        "prompt": "How would you diagnose and reduce API latency?",
        "competency": "Backend performance",
        "dimensions": [],
        "must_have": True,
    },
    {
        "id": "q-project-01",
        "order": 3,
        "type": "behavioral",
        "prompt": "What did you personally own in your most important project?",
        "competency": "Project ownership",
        "dimensions": [],
        "must_have": False,
    },
    {
        "id": "q-behavioral-01",
        "order": 4,
        "type": "behavioral",
        "prompt": "Describe a difficult production incident and what you changed afterward.",
        "competency": "Operational judgment",
        "dimensions": [],
        "must_have": False,
    },
]

PROFILES = [
    {
        "name": "Ada Lovelace",
        "technical": 96,
        "depth": 94,
        "followup": 92,
        "consistency": ConsistencyLabel.CONSISTENT,
        "ownership": OwnershipLevel.FULL_OWNER,
        "recommendation": Recommendation.ADVANCE,
        "integrity": 5,
    },
    {
        "name": "Grace Hopper",
        "technical": 92,
        "depth": 90,
        "followup": 88,
        "consistency": ConsistencyLabel.CONSISTENT,
        "ownership": OwnershipLevel.FULL_OWNER,
        "recommendation": Recommendation.ADVANCE,
        "integrity": 8,
    },
    {
        "name": "Margaret Hamilton",
        "technical": 88,
        "depth": 92,
        "followup": 84,
        "consistency": ConsistencyLabel.CONSISTENT,
        "ownership": OwnershipLevel.MAJOR_CONTRIBUTOR,
        "recommendation": Recommendation.ADVANCE,
        "integrity": 4,
    },
    {
        "name": "Linus Torvalds",
        "technical": 90,
        "depth": 84,
        "followup": 86,
        "consistency": ConsistencyLabel.CONSISTENT,
        "ownership": OwnershipLevel.FULL_OWNER,
        "recommendation": Recommendation.HOLD,
        "integrity": 12,
        "background_heavy": True,
    },
    {
        "name": "James Gosling",
        "technical": 82,
        "depth": 86,
        "followup": 78,
        "consistency": ConsistencyLabel.VAGUE,
        "ownership": OwnershipLevel.MAJOR_CONTRIBUTOR,
        "recommendation": Recommendation.ADVANCE,
        "integrity": 15,
    },
    {
        "name": "Barbara Liskov",
        "technical": 78,
        "depth": 80,
        "followup": 74,
        "consistency": ConsistencyLabel.CONSISTENT,
        "ownership": OwnershipLevel.MAJOR_CONTRIBUTOR,
        "recommendation": Recommendation.HOLD,
        "integrity": 72,
    },
    {
        "name": "Donald Knuth",
        "technical": 72,
        "depth": 70,
        "followup": 66,
        "consistency": ConsistencyLabel.VAGUE,
        "ownership": OwnershipLevel.MINOR_CONTRIBUTOR,
        "recommendation": Recommendation.HOLD,
        "integrity": 22,
    },
    {
        "name": "Edsger Dijkstra",
        "technical": 86,
        "depth": 82,
        "followup": 35,
        "consistency": ConsistencyLabel.INFLATED,
        "ownership": OwnershipLevel.MAJOR_CONTRIBUTOR,
        "recommendation": Recommendation.HOLD,
        "integrity": 18,
        "central_to_role": True,
        "resume_headline_claim": True,
    },
    {
        "name": "Ken Thompson",
        "technical": 94,
        "depth": 90,
        "followup": 88,
        "consistency": ConsistencyLabel.CONSISTENT,
        "ownership": OwnershipLevel.FULL_OWNER,
        "recommendation": Recommendation.HOLD,
        "integrity": 10,
        "hard_gate": True,
    },
    {
        "name": "Alan Turing",
        "technical": 58,
        "depth": 88,
        "followup": 32,
        "consistency": ConsistencyLabel.UNVERIFIABLE,
        "ownership": OwnershipLevel.UNCLEAR,
        "recommendation": Recommendation.REJECT,
        "integrity": 28,
        "flagship_project": True,
    },
]


def _stable_id(kind: str, index: int) -> str:
    return str(uuid5(DEMO_NAMESPACE, f"{kind}-{index}"))


def _band(score: int) -> str:
    """Band label for a 0-100 score, per the table in docs/rubric.md.

    Local rather than shared: nothing else needs it yet, and duplicating a
    five-line mapping beats starting a utils module (rule 4).
    """
    for floor, label in ((90, "expert"), (70, "strong"), (50, "adequate"), (25, "weak")):
        if score >= floor:
            return label
    return "poor"


def _evidence(profile: dict, question_id: str) -> RubricEvidence:
    quote = (
        f"For {question_id}, I measured the baseline, implemented the change, "
        f"and verified the result in production."
    )
    return RubricEvidence(
        quote=quote,
        rationale=f"Demo evidence for {profile['name']} supports the configured score band.",
    )


def _answer(
    profile: dict,
    question_id: str,
    question_type: ScoringQuestionType,
    *,
    include_technical: bool,
    include_ownership: bool,
) -> AnswerScore:
    evidence = _evidence(profile, question_id)
    ownership = profile["ownership"] if include_ownership else None
    technical = profile["technical"] if include_technical else None
    return AnswerScore(
        question_id=question_id,
        dimensions=[
            DimensionScore(
                key="depth",
                # DimensionScore moved to 0-100; this was still dividing by 20
                # for the old 1-5 scale, so every seeded demo scored 1-5 out of
                # 100 and looked like a failing candidate.
                score=profile["depth"],
                band=_band(profile["depth"]),
                evidence=evidence.quote,
                rationale=evidence.rationale,
            )
        ],
        weighted_score=max(1.0, min(5.0, profile["depth"] / 20)),
        followed_up=True,
        fixed_rubric=FixedRubricAssessment(
            question_type=question_type,
            technical_accuracy_score=technical,
            technical_accuracy_evidence=evidence if technical is not None else None,
            project_depth_score=profile["depth"],
            project_depth_evidence=evidence,
            ownership_level=ownership,
            ownership_evidence=evidence if ownership is not None else None,
            followup_resilience_score=profile["followup"],
            followup_resilience_evidence=evidence,
            consistency_label=profile["consistency"],
            consistency_evidence=evidence,
            central_to_role=bool(profile.get("central_to_role")),
            resume_headline_claim=bool(profile.get("resume_headline_claim")),
            flagship_project=bool(profile.get("flagship_project")),
        ),
        model_id="gemini-3.1-pro-preview",
        prompt_version="v2",
    )


def _answers(profile: dict) -> list[AnswerScore]:
    types = [
        ScoringQuestionType.BACKGROUND,
        ScoringQuestionType.TECHNICAL,
        ScoringQuestionType.PROJECT,
        ScoringQuestionType.BEHAVIORAL,
    ]
    if profile.get("background_heavy"):
        types = [
            ScoringQuestionType.BACKGROUND,
            ScoringQuestionType.BACKGROUND,
            ScoringQuestionType.BACKGROUND,
            ScoringQuestionType.TECHNICAL,
        ]

    return [
        _answer(
            profile,
            QUESTION_BANK[index]["id"],
            types[index],
            include_technical=index in (1, 2),
            include_ownership=index == 2,
        )
        for index in range(4)
    ]


def _question(question_id: str) -> dict:
    return next(question for question in QUESTION_BANK if question["id"] == question_id)


def _conversation(profile: dict, answer: AnswerScore, order: int) -> list[dict]:
    question = _question(answer.question_id)
    start_ms = order * 60000
    return [
        {
            "speaker": "candidate",
            "text": f"On that project, our team handled {question['competency'].lower()}.",
            "start_ms": start_ms,
            "end_ms": start_ms + 8000,
            "question_id": answer.question_id,
        },
        {
            "speaker": "interviewer",
            "text": "What specifically did you do, and how did you verify the result?",
            "start_ms": start_ms + 9000,
            "end_ms": start_ms + 13000,
            "question_id": answer.question_id,
            "is_follow_up": True,
        },
        {
            "speaker": "candidate",
            "text": answer.fixed_rubric.project_depth_evidence.quote,
            "start_ms": start_ms + 14000,
            "end_ms": start_ms + 29000,
            "question_id": answer.question_id,
        },
    ]


def _resume_claims(answer: AnswerScore) -> list[str]:
    question = _question(answer.question_id)
    return [f"Led work related to {question['competency'].lower()} on a production system."]


def _prior_relevant_claims(profile: dict, order: int) -> list[str]:
    return [
        f"Earlier, {profile['name']} described personally measuring and verifying question {i}."
        for i in range(1, order)
    ]


def _question_instance_id(interview_id: str, question_id: str) -> str:
    return str(uuid5(DEMO_NAMESPACE, f"{interview_id}-{question_id}"))


def _normalized_scoring_rows(
    org_id: str,
    interview_id: str,
    profile: dict,
    answer: AnswerScore,
    order: int,
) -> tuple[dict, list[dict], list[dict], dict]:
    """Build normalized persistence rows for one Gemini scoring request."""

    question_instance_id = _question_instance_id(interview_id, answer.question_id)
    question = _question(answer.question_id)
    fixed_rubric = answer.fixed_rubric
    if fixed_rubric is None:
        raise ValueError(f"Question {answer.question_id} has no rubric assessment")
    question_row = {
        "id": question_instance_id,
        "org_id": org_id,
        "interview_id": interview_id,
        "question_id": answer.question_id,
        "order_index": order,
        "question_text": question["prompt"],
        "question_type": fixed_rubric.question_type.value,
        "competency": question["competency"],
        "seniority": "senior",
        "resume_headline_claim": fixed_rubric.resume_headline_claim,
        "flagship_project": fixed_rubric.flagship_project,
        "central_to_role": fixed_rubric.central_to_role,
        "transcript_segment": fixed_rubric.project_depth_evidence.quote,
        "dimension_scores": [dimension.model_dump(mode="json") for dimension in answer.dimensions],
        "weighted_score": answer.weighted_score,
        "followed_up": answer.followed_up,
        "model_id": answer.model_id,
        "prompt_version": answer.prompt_version,
    }

    claims = []
    for source, values in (
        ("resume", _resume_claims(answer)),
        ("prior_answer", _prior_relevant_claims(profile, order)),
    ):
        for claim_index, claim_text in enumerate(values):
            claims.append(
                {
                    "id": str(
                        uuid5(
                            DEMO_NAMESPACE,
                            f"{question_instance_id}-{source}-{claim_index}",
                        )
                    ),
                    "org_id": org_id,
                    "question_instance_id": question_instance_id,
                    "source": source,
                    "claim_index": claim_index,
                    "claim_text": claim_text,
                }
            )

    turns = []
    for turn_index, turn in enumerate(_conversation(profile, answer, order)):
        turns.append(
            {
                "id": str(uuid5(DEMO_NAMESPACE, f"{question_instance_id}-turn-{turn_index}")),
                "org_id": org_id,
                "question_instance_id": question_instance_id,
                "turn_index": turn_index,
                "speaker": turn["speaker"],
                "text": turn["text"],
                "start_ms": turn["start_ms"],
                "end_ms": turn["end_ms"],
                "is_follow_up": turn.get("is_follow_up", False),
            }
        )

    def evidence_columns(prefix: str, evidence: RubricEvidence | None) -> dict[str, str | None]:
        return {
            f"{prefix}_quote": evidence.quote if evidence else None,
            f"{prefix}_rationale": evidence.rationale if evidence else None,
        }

    assessment = {
        "id": str(uuid5(DEMO_NAMESPACE, f"{question_instance_id}-rubric-assessment")),
        "org_id": org_id,
        "question_instance_id": question_instance_id,
        "technical_accuracy_score": fixed_rubric.technical_accuracy_score,
        **evidence_columns("technical_accuracy", fixed_rubric.technical_accuracy_evidence),
        "project_depth_score": fixed_rubric.project_depth_score,
        **evidence_columns("project_depth", fixed_rubric.project_depth_evidence),
        "ownership_level": (
            fixed_rubric.ownership_level.value if fixed_rubric.ownership_level else None
        ),
        **evidence_columns("ownership", fixed_rubric.ownership_evidence),
        "followup_resilience_score": fixed_rubric.followup_resilience_score,
        **evidence_columns("followup_resilience", fixed_rubric.followup_resilience_evidence),
        "consistency_label": fixed_rubric.consistency_label.value,
        **evidence_columns("consistency", fixed_rubric.consistency_evidence),
        "model_id": answer.model_id,
        "prompt_version": answer.prompt_version,
    }

    return question_row, claims, turns, assessment


def build_results(org_id: str) -> list[InterviewResult]:
    results: list[InterviewResult] = []
    for index, profile in enumerate(PROFILES, start=1):
        base = InterviewResult(
            interview_id=_stable_id("interview", index),
            org_id=org_id,
            application_id=_stable_id("application", index),
            job_id=JOB_ID,
            answers=_answers(profile),
            holistic=HolisticScore(
                score=max(1.0, min(5.0, profile["depth"] / 20)),
                strengths=["Evidence-backed technical reasoning"],
                concerns=[] if profile["followup"] >= 50 else ["Weak follow-up resilience"],
                representative_quote=_evidence(profile, "q-project-01").quote,
                model_id="gemini-3.1-pro-preview",
                prompt_version="v1",
            ),
            role_fit=max(1.0, min(5.0, profile["technical"] / 20)),
            overall=3.0,
            recommendation=profile["recommendation"],
            hard_gate_applied=bool(profile.get("hard_gate")),
            integrity=IntegrityReport(
                score=profile["integrity"],
                events=[],
                summary="Synthetic demo integrity report.",
            ),
            rubric_version="demo-rubric-v2",
            scored_at=SCORED_AT + timedelta(minutes=index),
        )
        results.append(apply_rubric_to_result(base, "senior"))

    scores = [result.composite_score for result in results]
    for result in results:
        result.percentile = round(
            100 * sum(score <= result.composite_score for score in scores) / len(scores),
            1,
        )
    return results


def _ensure_org() -> str:
    existing = db().table("organization").select("id").eq("slug", ORG_SLUG).execute().data
    if existing:
        return existing[0]["id"]
    return (
        db()
        .table("organization")
        .insert({"name": ORG_NAME, "slug": ORG_SLUG, "plan": "free"})
        .execute()
        .data[0]["id"]
    )


def _require_normalized_scoring_schema() -> None:
    try:
        db().table("question_instance").select(
            "question_text,question_type,competency,seniority,"
            "resume_headline_claim,flagship_project,central_to_role"
        ).limit(1).execute()
        db().table("question_scoring_claim").select("id").limit(1).execute()
        db().table("question_conversation_turn").select("id").limit(1).execute()
        db().table("question_rubric_assessment").select("id").limit(1).execute()
    except Exception as exc:
        raise SystemExit(
            "Normalized question scoring tables are missing. Apply migration "
            "20260823110000_lane2_normalize_question_scoring_input.sql and migration "
            "20260823111000_lane2_normalize_question_rubric_assessment.sql, then rerun the seed."
        ) from exc


def _seed_parent_rows(org_id: str, results: list[InterviewResult]) -> None:
    db().table("job").upsert(
        {
            "id": JOB_ID,
            "org_id": org_id,
            "title": "Senior Backend Engineer - Scoring Demo",
            "role_family": "Backend Engineering",
            "seniority": "senior",
            "jd_text": "Design reliable APIs, diagnose production systems, and lead projects.",
            "status": "open",
            "question_bank": QUESTION_BANK,
            "question_bank_status": "ready",
            "rubric_version": "demo-rubric-v2",
        },
        on_conflict="id",
    ).execute()

    candidates = []
    applications = []
    interviews = []
    for index, (profile, result) in enumerate(zip(PROFILES, results, strict=True), start=1):
        candidate_id = _stable_id("candidate", index)
        candidates.append(
            {
                "id": candidate_id,
                "org_id": org_id,
                "email": f"score-demo-{index}@example.com",
                "full_name": profile["name"],
                "location": "Remote",
            }
        )
        applications.append(
            {
                "id": result.application_id,
                "org_id": org_id,
                "job_id": JOB_ID,
                "candidate_id": candidate_id,
                "status": "scored",
                "resume_url": f"demo://resumes/score-demo-{index}.pdf",
                "parsed_resume": {"summary": f"Synthetic resume for {profile['name']}"},
                "consent_given_at": SCORED_AT.isoformat(),
            }
        )
        interviews.append(
            {
                "id": result.interview_id,
                "org_id": org_id,
                "application_id": result.application_id,
                "job_id": JOB_ID,
                "status": "completed",
                "started_at": (result.scored_at - timedelta(minutes=30)).isoformat(),
                "ended_at": (result.scored_at - timedelta(minutes=2)).isoformat(),
                "transcript": [
                    turn
                    for order, answer in enumerate(result.answers, start=1)
                    for turn in _conversation(profile, answer, order)
                ],
                "model_id": "gemini-2.5-flash-native-audio-preview-12-2025",
                "prompt_version": "v1",
                "overall": result.overall,
                "percentile": result.percentile,
                "recommendation": result.recommendation.value,
                "hard_gate_applied": result.hard_gate_applied,
                "role_fit": result.role_fit,
                "holistic": result.holistic.model_dump(mode="json"),
                "integrity": result.integrity.model_dump(mode="json"),
                "rubric_version": result.rubric_version,
                "scored_at": result.scored_at.isoformat(),
            }
        )

    db().table("candidate").upsert(candidates, on_conflict="id").execute()
    db().table("application").upsert(applications, on_conflict="id").execute()
    db().table("interview").upsert(interviews, on_conflict="id").execute()


def _seed_scores(org_id: str, results: list[InterviewResult]) -> None:
    question_instances = []
    scoring_claims = []
    conversation_turns = []
    rubric_assessments = []
    for index, result in enumerate(results, start=1):
        for order, answer in enumerate(result.answers, start=1):
            question_row, claim_rows, turn_rows, assessment_row = _normalized_scoring_rows(
                org_id,
                result.interview_id,
                PROFILES[index - 1],
                answer,
                order,
            )
            question_instances.append(question_row)
            scoring_claims.extend(claim_rows)
            conversation_turns.extend(turn_rows)
            rubric_assessments.append(assessment_row)

    score_rows = []
    for index, result in enumerate(results, start=1):
        row = build_interview_score_row(result)
        row["id"] = _stable_id("score", index)
        score_rows.append(row)

    db().table("question_instance").upsert(question_instances, on_conflict="id").execute()
    db().table("question_scoring_claim").upsert(
        scoring_claims,
        on_conflict="question_instance_id,source,claim_index",
    ).execute()
    db().table("question_conversation_turn").upsert(
        conversation_turns,
        on_conflict="question_instance_id,turn_index",
    ).execute()
    db().table("question_rubric_assessment").upsert(
        rubric_assessments,
        on_conflict="question_instance_id",
    ).execute()
    db().table("interview_score").upsert(score_rows, on_conflict="id").execute()


def _print_results(results: list[InterviewResult]) -> None:
    print(f"\n{'Candidate':24} {'Score':>7} {'Pct':>6}  Review reasons")
    print("-" * 88)
    for profile, result in sorted(
        zip(PROFILES, results, strict=True),
        key=lambda item: item[1].composite_score,
        reverse=True,
    ):
        reasons = ", ".join(reason.value for reason in result.review_reasons) or "none"
        print(
            f"{profile['name']:24} {result.composite_score:7.2f} "
            f"{result.percentile:6.1f}  {reasons}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="calculate without writing")
    args = parser.parse_args()

    if args.dry_run:
        results = build_results("00000000-0000-4000-8000-000000000001")
        _print_results(results)
        print("\nDry run only; database was not changed.")
        return

    _require_normalized_scoring_schema()
    org_id = _ensure_org()
    results = build_results(org_id)
    _seed_parent_rows(org_id, results)
    _seed_scores(org_id, results)
    _print_results(results)
    print(f"\nSeeded 10 scoring examples for job_id={JOB_ID} org_id={org_id}")


if __name__ == "__main__":
    main()
