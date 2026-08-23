"""Structural tests for the question_builder workflow.

No Gemini calls: these check that the graph is wired the way the design says and
that the typed boundary rejects malformed rubrics. Whether the anchors are
*good* is a human judgement, not something a test can assert — but whether they
are portable is checked by eye against real jobs, per docs/rubric.md.
"""

import json

import pytest
from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent

from intake.question_builder import MAX_REVISIONS, build_workflow, parse_rubric


def test_workflow_has_the_designed_shape():
    wf = build_workflow()
    assert isinstance(wf, SequentialAgent)

    extractor, rubric, loop = wf.sub_agents

    assert isinstance(extractor, LlmAgent)
    assert extractor.output_key == "competencies"

    assert isinstance(rubric, LlmAgent)
    assert rubric.output_key == "draft_rubric"

    assert isinstance(loop, LoopAgent)
    assert loop.max_iterations == MAX_REVISIONS


def test_loop_can_terminate_early():
    """Without an escalate path the loop always burns every iteration, even on a
    rubric that was already correct."""
    loop = build_workflow().sub_agents[2]
    validator, reviser = loop.sub_agents
    assert [t.__name__ for t in validator.tools] == ["exit_loop"]
    assert reviser.output_key == "draft_rubric"  # reviser overwrites the draft


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
    assert len(leaves) == 4
    for agent in leaves:
        assert agent.model, f"{agent.name} has no model"
        assert callable(agent.instruction)


# --- the typed boundary ---------------------------------------------------


def _competency(key: str = "databases", **overrides) -> dict:
    return {
        "key": key,
        "name": "Database performance",
        "why": "Shows they can reason about why a system got slower.",
        "kind": "technical",
        "must_have": True,
        "weight": 0.3,
        "dimensions": [
            {
                "key": "correctness",
                "weight": 1.0,
                "anchors": {
                    1: "No relevant approach offered.",
                    2: "Names one idea without reasoning.",
                    3: "Describes a systematic approach.",
                    4: "Names a trade-off and says which side they picked.",
                    5: "Anticipates a second-order failure mode.",
                },
            }
        ],
        **overrides,
    }


VALID = {"competencies": [_competency()], "version": "v1"}


def test_parses_a_valid_rubric():
    assert len(parse_rubric(VALID).competencies) == 1


def test_parses_json_string_and_fenced_json():
    assert len(parse_rubric(json.dumps(VALID)).competencies) == 1
    assert len(parse_rubric(f"```json\n{json.dumps(VALID)}\n```").competencies) == 1


def test_accepts_a_bare_competency_list():
    """The writer occasionally returns the list rather than the wrapper. That is
    unambiguous, so it is normalised rather than rejected."""
    assert len(parse_rubric([_competency()]).competencies) == 1


def test_rejects_duplicate_keys():
    """Two competencies with one key means questions tagged with it get whichever
    anchors the lookup happens to find first."""
    with pytest.raises(ValueError, match="duplicate"):
        parse_rubric({"competencies": [_competency(), _competency()]})


def test_rejects_reserved_poison_key():
    """intake/questions.py routes `poison` to the integrity dimension. A real
    competency by that name would silently lose its anchors."""
    with pytest.raises(ValueError, match="reserved"):
        parse_rubric({"competencies": [_competency(key="poison")]})


@pytest.mark.parametrize(
    "bad",
    [
        {"competencies": []},                          # nothing to score
        {"competencies": [{"key": "x"}]},              # missing required fields
        {"competencies": [_competency(dimensions=[])]},  # no anchors
        "not json at all",
        {"unexpected": "shape"},
    ],
)
def test_rejects_malformed_rubrics(bad):
    """Malformed output must fail here rather than being stored — a broken rubric
    surfaces later as an unscoreable interview, long after it can be traced
    back."""
    with pytest.raises(Exception):
        parse_rubric(bad)
