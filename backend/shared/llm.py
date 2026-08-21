"""The only place Gemini is called from.

Every LLM task goes through `run()`. Prompt text, model, and version come from
llm/registry.json — never from a string literal in a route handler. That is what
makes swapping a model or bumping a prompt a config edit instead of a code edit.

The returned Provenance must be persisted alongside whatever the call produced.
Scores without provenance are not comparable across model or prompt changes,
which for a leaderboard is a correctness bug, not a logging gap (D5).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from .config import get_settings

T = TypeVar("T", bound=BaseModel)

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO_ROOT / "llm" / "registry.json"
PROMPTS_DIR = REPO_ROOT / "llm" / "prompts"


class Provenance(BaseModel):
    """Persist this next to every LLM-derived value."""

    task: str
    model_id: str
    prompt_version: str


class TaskConfig(BaseModel):
    prompt: str
    model: str
    version: str


@lru_cache(maxsize=1)
def _registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text())["tasks"]


@lru_cache(maxsize=64)
def task_config(task: str) -> TaskConfig:
    """Resolve a task key, supporting dotted paths for nested workflow agents.

    'resume-parse' and 'question-builder.validator' both work — ADK sub-agents
    get their prompt and model from the same registry as everything else (D21),
    so there is one place to look when a model needs changing.
    """
    node: Any = _registry()
    for part in task.split("."):
        if not isinstance(node, dict) or part not in node:
            raise KeyError(f"Unknown LLM task '{task}' — check llm/registry.json")
        node = node[part]
    return TaskConfig(**node)


@lru_cache(maxsize=64)
def prompt_text(task: str) -> str:
    """The system prompt for a task, loaded from llm/prompts/."""
    return (PROMPTS_DIR / task_config(task).prompt).read_text()


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    return genai.Client(api_key=get_settings().gemini_api_key)


def pdf_part(data: bytes) -> types.Part:
    """Wrap a PDF for native document input.

    Gemini reads PDFs directly — layout, tables, and columns included — which is
    why there is no resume-parsing vendor in this stack (D10).
    """
    return types.Part.from_bytes(data=data, mime_type="application/pdf")


def run(
    task: str,
    schema: type[T],
    *,
    user_content: str | list,
    extra_instructions: str | None = None,
) -> tuple[T, Provenance]:
    """Run a registered task and return validated output plus provenance.

    Args:
        task: key in llm/registry.json, dotted for nested entries.
        schema: Pydantic model. Passed to Gemini as response_schema, so the
            response is constrained to it rather than parsed hopefully.
        user_content: str, or a list of parts for multimodal input (e.g. a PDF
            resume alongside a text instruction).
        extra_instructions: appended to the system prompt for per-call context
            such as the job's requirements.

    Candidate text — resume content, interview answers — is untrusted input. It
    belongs in `user_content`, never in `extra_instructions` and never
    concatenated into the system prompt, or a candidate can write instructions
    to the model that is judging them.
    """
    cfg = task_config(task)
    system = prompt_text(task)
    if extra_instructions:
        system = f"{system}\n\n{extra_instructions}"

    response = _client().models.generate_content(
        model=cfg.model,
        contents=user_content,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )

    parsed = response.parsed
    if parsed is None:
        raise ValueError(
            f"Task '{task}' returned no parseable output "
            f"(model={cfg.model}, prompt={cfg.prompt})"
        )

    return parsed, Provenance(task=task, model_id=cfg.model, prompt_version=cfg.version)
