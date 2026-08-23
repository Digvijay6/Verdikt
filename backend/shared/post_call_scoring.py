"""Single-prompt Gemini scoring for one completed interview."""

from __future__ import annotations

from collections.abc import Callable

from shared import llm
from shared.llm import Provenance
from shared.models.scoring import (
    AnswerScore,
    HolisticScore,
    ScoreAnswerResponse,
    ScoreInterviewInput,
    ScoreInterviewResponse,
)

ScoreInterviewRunner = Callable[..., tuple[ScoreInterviewResponse, Provenance]]


def score_interview(
    package: ScoreInterviewInput,
    *,
    runner: ScoreInterviewRunner = llm.run,
) -> tuple[list[AnswerScore], HolisticScore]:
    """Score every question in exactly one Gemini call and preserve bank order."""

    expected_ids = [question.question_id for question in package.questions]
    if len(expected_ids) != len(set(expected_ids)):
        raise ValueError("question_id values must be unique within an interview")

    response, provenance = runner(
        "score-interview",
        ScoreInterviewResponse,
        user_content=package.model_dump_json(),
    )
    answers_by_id = _validated_answers_by_id(response.answers, expected_ids)
    inputs_by_id = {question.question_id: question for question in package.questions}

    answers = []
    for question_id in expected_ids:
        output = answers_by_id[question_id]
        question = inputs_by_id[question_id]
        trusted_rubric = output.fixed_rubric.model_copy(
            update={
                "question_type": question.question_type,
                "central_to_role": question.resume_context.central_to_role,
                "resume_headline_claim": question.resume_context.is_resume_headline_claim,
                "flagship_project": question.resume_context.is_flagship_project,
            }
        )
        answers.append(
            AnswerScore(
                question_id=question_id,
                dimensions=output.dimensions,
                weighted_score=output.weighted_score,
                fixed_rubric=trusted_rubric,
                followed_up=any(turn.is_follow_up for turn in question.conversation),
                model_id=provenance.model_id,
                prompt_version=provenance.prompt_version,
            )
        )

    holistic = HolisticScore(
        score=response.holistic_score,
        strengths=response.strengths,
        concerns=response.concerns,
        representative_quote=response.representative_quote,
        model_id=provenance.model_id,
        prompt_version=provenance.prompt_version,
    )
    return answers, holistic


def _validated_answers_by_id(
    answers: list[ScoreAnswerResponse],
    expected_ids: list[str],
) -> dict[str, ScoreAnswerResponse]:
    returned_ids = [answer.question_id for answer in answers]
    if len(returned_ids) != len(set(returned_ids)):
        raise ValueError("score-interview returned duplicate question_id values")
    if set(returned_ids) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(returned_ids))
        unexpected = sorted(set(returned_ids) - set(expected_ids))
        raise ValueError(
            f"score-interview question mismatch: missing={missing}, unexpected={unexpected}"
        )
    return {answer.question_id: answer for answer in answers}
