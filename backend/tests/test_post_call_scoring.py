from scripts.score_job_interviews import build_interview_package
from shared.llm import Provenance
from shared.models.job import Question
from shared.models.scoring import (
    ConsistencyLabel,
    DimensionScore,
    FixedRubricAssessment,
    RubricEvidence,
    ScoreAnswerResponse,
    ScoreInterviewResponse,
    ScoringQuestionType,
)
from shared.post_call_scoring import score_interview


def _questions() -> list[Question]:
    return [
        Question.model_validate(
            {
                "id": f"q-{index}",
                "order": index,
                "type": "technical",
                "prompt": f"Question {index}?",
                "competency": "Backend performance",
                "dimensions": [
                    {
                        "key": "depth",
                        "weight": 1.0,
                        "anchors": {score: f"Anchor {score}" for score in range(1, 6)},
                    }
                ],
                "must_have": index == 1,
            }
        )
        for index in (1, 2)
    ]


def _package():
    transcript = []
    for index in (1, 2):
        transcript.extend(
            [
                {
                    "speaker": "agent",
                    "text": f"Question {index}?",
                    "start_ms": index * 1000,
                    "end_ms": index * 1000 + 100,
                    "question_id": f"q-{index}",
                },
                {
                    "speaker": "candidate",
                    "text": f"Answer {index}",
                    "start_ms": index * 1000 + 101,
                    "end_ms": index * 1000 + 500,
                    "question_id": f"q-{index}",
                },
            ]
        )
    return build_interview_package(
        {"id": "interview-1", "transcript": transcript},
        _questions(),
        seniority="senior",
        parsed_resume={"skills": ["Python", "PostgreSQL"]},
    )


def test_score_interview_uses_one_call_and_preserves_question_order() -> None:
    calls = 0

    def runner(task: str, schema: type, *, user_content: str):
        nonlocal calls
        calls += 1
        assert task == "score-interview"
        assert schema is ScoreInterviewResponse
        assert '"interview_id":"interview-1"' in user_content
        evidence = RubricEvidence(quote="Answer 1", rationale="Evidence matches")
        answers = [
            ScoreAnswerResponse(
                question_id=question_id,
                dimensions=[
                    DimensionScore(
                        key="depth",
                        score=80,
                        band="strong",
                        evidence=evidence.quote,
                        rationale=evidence.rationale,
                    )
                ],
                weighted_score=4.0,
                fixed_rubric=FixedRubricAssessment(
                    question_type=ScoringQuestionType.BACKGROUND,
                    project_depth_score=80,
                    project_depth_evidence=evidence,
                    consistency_label=ConsistencyLabel.CONSISTENT,
                    consistency_evidence=evidence,
                ),
            )
            for question_id in ("q-2", "q-1")
        ]
        return (
            ScoreInterviewResponse(
                answers=answers,
                holistic_score=4.0,
                strengths=["Specific answers"],
                concerns=[],
                representative_quote="Answer 1",
            ),
            Provenance(task=task, model_id="gemini-test", prompt_version="v1-test"),
        )

    answers, holistic = score_interview(_package(), runner=runner)

    assert calls == 1
    assert [answer.question_id for answer in answers] == ["q-1", "q-2"]
    assert answers[0].fixed_rubric.question_type is ScoringQuestionType.TECHNICAL
    assert answers[0].fixed_rubric.central_to_role is True
    assert answers[0].model_id == "gemini-test"
    assert holistic.score == 4.0


def test_build_interview_package_includes_all_questions_and_resume_context() -> None:
    package = _package()

    assert len(package.questions) == 2
    assert package.questions[0].resume_context.central_to_role is True
    assert package.questions[0].resume_context.relevant_claims == ["Skills: Python, PostgreSQL"]
    assert package.questions[1].prior_relevant_claims == ["Answer 1"]
