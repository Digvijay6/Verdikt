"""ADK agent: check a candidate's claims against the links they gave us.

This is the one genuinely agentic thing in lane 1. `question_builder` is a
fixed pipeline — the trajectory never varies, only the content does. Here each
finding decides the next call: a repo whose name matches a claimed technology
is worth opening; one that is a two-commit fork is not. That is what tools and
a model-driven trajectory are actually for.

**The asymmetry is the whole design (D32).** A supported claim raises
confidence. A contradicted claim lowers it. **Finding nothing does neither.**
Most professional work lives in private company repositories, so absence of
public evidence says nothing about ability — and penalising it would quietly
punish anyone whose best work is behind an employer's firewall.
"""

from __future__ import annotations

import asyncio
import json
import logging
from enum import StrEnum

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools import ToolContext
from google.genai import types
from pydantic import BaseModel, Field

from shared import llm
from shared.models.candidate import ParsedResume

from . import github

log = logging.getLogger(__name__)

APP_NAME = "candidate_evidence"

# Unbounded exploration is slow and expensive, and the marginal repo is rarely
# the informative one. Hitting the cap is normal completion, not failure.
TOOL_BUDGET = 12
_BUDGET_KEY = "tool_calls_used"


class Verdict(StrEnum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    NOT_FOUND = "not_found"


class Finding(BaseModel):
    claim: str = Field(description="The resume claim being checked, quoted")
    verdict: Verdict
    detail: str = Field(description="What was actually found, specifically")
    source_url: str | None = Field(None, description="Where it was found")


class CandidateEvidence(BaseModel):
    """What the screen receives. Never a score — the screen reasons about this
    alongside everything else, so a recruiter can see the reasoning."""

    findings: list[Finding] = []
    summary: str = Field(description="One or two sentences, neutral in tone")
    profile_url: str | None = None


# --- tools ----------------------------------------------------------------


def _spend(tool_context: ToolContext) -> bool:
    """Take one unit of budget. False once it is gone."""
    used = tool_context.state.get(_BUDGET_KEY, 0)
    if used >= TOOL_BUDGET:
        return False
    tool_context.state[_BUDGET_KEY] = used + 1
    return True


def get_profile(username: str, tool_context: ToolContext) -> dict:
    """Fetch a GitHub user's public profile.

    Args:
        username: the GitHub login, without the @ or any URL.
    """
    if not _spend(tool_context):
        return {"error": "budget_exhausted", "note": "Summarise what you have."}
    p = github.profile(username)
    if p is None:
        # Not a failure that reflects on the candidate: profiles get renamed,
        # made private, or the API rate-limits us.
        return {"found": False, "note": "Profile unavailable. This is not evidence against any claim."}
    return {"found": True, "profile": p}


def list_repositories(username: str, tool_context: ToolContext) -> dict:
    """List a user's non-forked public repositories, most recently pushed first.

    Args:
        username: the GitHub login.
    """
    if not _spend(tool_context):
        return {"error": "budget_exhausted", "note": "Summarise what you have."}
    repos = github.repositories(username)
    return {"count": len(repos), "repositories": repos}


def inspect_repository(username: str, repo: str, tool_context: ToolContext) -> dict:
    """Read one repository in detail: languages by bytes, and its README.

    Use this to tell a real project from a tutorial follow-along.

    Args:
        username: the GitHub login.
        repo: the repository name.
    """
    if not _spend(tool_context):
        return {"error": "budget_exhausted", "note": "Summarise what you have."}
    d = github.repository_detail(username, repo)
    if d is None:
        return {"found": False, "note": "Repository unavailable. Not evidence against any claim."}
    return {"found": True, "repository": d}


# --- the agent ------------------------------------------------------------


def build_agent() -> LlmAgent:
    cfg = llm.task_config("candidate-evidence")
    return LlmAgent(
        name="candidate_evidence",
        model=cfg.model,
        instruction=llm.prompt_text("candidate-evidence"),
        tools=[get_profile, list_repositories, inspect_repository],
        output_key="evidence",
    )


def structure(notes: str) -> CandidateEvidence:
    """Turn the agent's prose into the typed object.

    A second call rather than an output schema on the agent itself: ADK cannot
    combine `output_schema` with tools, and the agent needs tools. So it
    explores freely and this converts, with Gemini's response_schema
    guaranteeing the shape rather than hoping for well-formed JSON.
    """
    evidence, _ = llm.run(
        "candidate-evidence-format",
        CandidateEvidence,
        user_content=notes,
    )
    return evidence


def github_username(resume: ParsedResume) -> str | None:
    """The GitHub link the candidate chose to give us, if any."""
    for link in resume.links:
        if "github.com" in link.lower():
            name = github.username_from_url(link)
            if name:
                return name
    return None


async def gather_async(
    resume: ParsedResume, jd_text: str, username: str
) -> CandidateEvidence:
    claims = {
        "skills_claimed": resume.skills,
        "roles": [
            {"company": e.company, "title": e.title, "summary": e.summary}
            for e in resume.employment
        ],
    }

    runner = InMemoryRunner(agent=build_agent(), app_name=APP_NAME)
    try:
        session = await runner.session_service.create_session(
            app_name=APP_NAME, user_id=username, state={_BUDGET_KEY: 0}
        )
        message = (
            f"GitHub username: {username}\n\n"
            f"Claims from their resume:\n{json.dumps(claims, indent=2)}\n\n"
            f"Role they applied for:\n{jd_text[:2000]}"
        )
        async for _ in runner.run_async(
            user_id=username,
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        ):
            pass

        final = await runner.session_service.get_session(
            app_name=APP_NAME, user_id=username, session_id=session.id
        )
        notes = final.state.get("evidence") or ""
        used = final.state.get(_BUDGET_KEY, 0)
        log.info("evidence for %s: %d tool calls", username, used)
        if not notes.strip():
            return CandidateEvidence(
                summary="No evidence gathered.",
                profile_url=f"https://github.com/{username}",
            )
        return structure(notes)
    finally:
        await runner.close()


def gather(resume: ParsedResume, jd_text: str) -> CandidateEvidence | None:
    """Collect evidence, or return None if there is nothing to check.

    Never raises. Evidence is an enhancement to screening, not a precondition
    for it — an outage here must not stop someone's application being read.
    """
    username = github_username(resume)
    if not username:
        return None
    try:
        return asyncio.run(gather_async(resume, jd_text, username))
    except Exception:
        log.exception("evidence gathering failed for github user %s", username)
        return None
