from scripts.seed_scoring_examples import PROFILES, _answers, _normalized_scoring_rows


def test_normalized_rows_contain_complete_per_question_context() -> None:
    answer = _answers(PROFILES[7])[2]

    question, claims, turns, assessment = _normalized_scoring_rows(
        "00000000-0000-4000-8000-000000000001",
        "00000000-0000-4000-8000-000000000002",
        PROFILES[7],
        answer,
        3,
    )

    assert "scoring_input" not in question
    assert "fixed_rubric" not in question
    assert question["question_id"] == "q-project-01"
    assert question["question_type"] == "project"
    assert question["seniority"] == "senior"
    assert question["resume_headline_claim"] is True
    assert question["flagship_project"] is False
    assert question["central_to_role"] is True
    assert [claim["source"] for claim in claims] == [
        "resume",
        "prior_answer",
        "prior_answer",
    ]
    assert claims[0]["claim_text"] == (
        "Led work related to project ownership on a production system."
    )
    assert len(turns) == 3
    assert turns[1]["speaker"] == "interviewer"
    assert turns[1]["is_follow_up"] is True
    assert assessment["technical_accuracy_score"] == 86
    assert assessment["project_depth_score"] == 82
    assert assessment["ownership_level"] == "major_contributor"
    assert assessment["followup_resilience_score"] == 35
    assert assessment["consistency_label"] == "inflated"
    assert assessment["project_depth_quote"]
    assert assessment["model_id"] == "gemini-3.1-pro-preview"
    assert assessment["prompt_version"] == "v2"
