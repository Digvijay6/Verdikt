"""The only place Gemini is called from.

Every LLM task goes through `run()`. Prompt text, model, and version come from
llm/registry.json — never from a string literal in a route handler. That is what
makes swapping a model or bumping a prompt a config edit instead of a code edit.

The returned Provenance must be persisted alongside whatever the call produced.
Scores without provenance are not comparable across model or prompt changes,
which for a leaderboard is a correctness bug, not a logging gap.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from .config import settings

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
def _registry() -> dict[str, TaskConfig]:
    raw = json.loads(REGISTRY_PATH.read_text())
    return {name: TaskConfig(**cfg) for name, cfg in raw["tasks"].items()}


@lru_cache(maxsize=32)
def _prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text()


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    return genai.Client(api_key=settings.gemini_api_key)


def run(
    task: str,
    schema: type[T],
    *,
    user_content: str | list,
    extra_instructions: str | None = None,
) -> tuple[T, Provenance]:
    """Run a registered task and return validated output plus provenance.

    Args:
        task: key in llm/registry.json
        schema: Pydantic model. Passed to Gemini as response_schema, so the
            response is constrained to it rather than parsed hopefully.
        user_content: str, or a list of parts for multimodal input (e.g. a PDF
            resume alongside a text instruction).
        extra_instructions: appended to the system prompt for per-call context
            such as the job's must-have criteria. Never put candidate-supplied
            text here — see the untrusted-input note below.

    Candidate text (resume content, interview answers) is untrusted input. It
    belongs in `user_content`, never concatenated into the system prompt, or a
    candidate can instruct the judge that scores them.
    """
    cfg = _registry()[task]
    system = _prompt(cfg.prompt)
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

    return response.parsed, Provenance(
        task=task, model_id=cfg.model, prompt_version=cfg.version
    )
