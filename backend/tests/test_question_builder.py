"""Structural tests for the question_builder workflow.

No Gemini calls: these check that the graph is wired the way the design says and
that the typed boundary rejects malformed banks. The quality of the questions
themselves is a human judgement, not something a test can assert.
"""

import json

import pytest
from google.adk.agents import LlmAgent, LoopAgent, ParallelAgent, SequentialAgent

from intake.question_builder import MAX_REVISIONS, build_workflow, parse_bank


def test_workflow_has_the_designed_shape():
    wf = build_workflow()
    assert isinstance(wf, SequentialAgent)

    extractor, draft, rubric, loop = wf.sub_agents

    assert isinstance(extractor, LlmAgent)
    assert extractor.output_key == "competencies"

    assert isinstance(draft, ParallelAgent)
    assert {a.output_key for a in draft.sub_agents} == {
        "technical_questions",
        "behavioral_questions",
        "poison_question",
    }

    assert isinstance(rubric, LlmAgent)
    assert rubric.output_key == "draft_bank"

    assert isinstance(loop, LoopAgent)
    assert loop.max_iterations == MAX_REVISIONS


def test_loop_can_terminate_early():
    """Without an escalate path the loop always burns every iteration, even on a
    bank that was already correct."""
    loop = build_workflow().sub_agents[3]
    validator, reviser = loop.sub_agents
    assert [t.__name__ for t in validator.tools] == ["exit_loop"]
    assert reviser.output_key == "draft_bank"  # reviser overwrites the draft


def test_exit_loop_sets_escalate():
    from unittest.mock import MagicMock

    from intake.question_builder import exit_loop

    ctx = MagicMock()
    exit_loop(ctx)
    assert ctx.actions.escalate is True


def test_every_agent_resolves_a_prompt_and_model():
    """Catches a registry key or prompt file going missing — which would
    otherwise only surface mid-build, after a job was created."""

    def walk(agent):
        yield agent
        for child in agent.sub_agents or []:
            yield from walk(child)

    leaves = [a for a in walk(build_workflow()) if isinstance(a, LlmAgent)]
    assert len(leaves) == 7
    for agent in leaves:
        assert agent.model, f"{agent.name} has no model"
        assert callable(agent.instruction)


# --- the typed boundary ---------------------------------------------------

VALID = [
    {
        "id": "q1",
        "order": 1,
        "type": "technical",
        "prompt": "How would you approach a query that has gotten slower?",
        "competency": "databases",
        "must_have": True,
        "dimensions": [
            {
                "key": "correctness",
                "weight": 1.0,
                "anchors": {
                    1: "No relevant approach offered.",
                    2: "Names one idea without reasoning.",
                    3: "Describes a systematic approach.",
                    4: "Names a trade-off and picks a side.",
                    5: "Anticipates a second-order failure mode.",
                },
            }
        ],
    }
]


def test_parses_a_valid_bank():
    assert len(parse_bank(VALID)) == 1


def test_parses_json_string_and_fenced_json():
    assert len(parse_bank(json.dumps(VALID))) == 1
    assert len(parse_bank(f"```json\n{json.dumps(VALID)}\n```")) == 1


def test_unwraps_questions_key():
    assert len(parse_bank({"questions": VALID})) == 1


@pytest.mark.parametrize(
    "bad",
    [
        [],                                    # empty bank
        [{"id": "q1"}],                        # missing required fields
        "not json at all",
        {"unexpected": "shape"},
    ],
)
def test_rejects_malformed_banks(bad):
    """Malformed output must fail here rather than being stored — a broken bank
    surfaces later as a broken interview, long after it can be traced back."""
    with pytest.raises(Exception):
        parse_bank(bad)
