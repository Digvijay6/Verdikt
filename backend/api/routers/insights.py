"""LANE 3 — leaderboard, candidate detail, recruiter chat, outreach.

The chat does not need RAG. A full interview — transcript, per-question scores
with evidence quotes, resume, integrity report — is roughly 10-15k tokens, and
Gemini's context window is 1M. Put the whole thing in the prompt. No embeddings,
no vector store, no chunking, and citations get more accurate rather than less.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from shared.models.scoring import InterviewResult

from ..deps import Recruiter, current_recruiter

router = APIRouter(prefix="/insights", tags=["insights"])


class LeaderboardEntry(BaseModel):
    application_id: str
    interview_id: str
    candidate_name: str
    overall: float
    percentile: float | None
    recommendation: str
    integrity_score: int
    flagged: bool


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
def leaderboard(
    job_id: str,
    recruiter: Recruiter = Depends(current_recruiter),
) -> list[LeaderboardEntry]:
    """Ranked within one job only. Scores are not comparable across jobs —
    different rubrics, different weights, sometimes different models."""
    raise NotImplementedError


@router.get("/interviews/{interview_id}", response_model=InterviewResult)
def interview_detail(
    interview_id: str,
    recruiter: Recruiter = Depends(current_recruiter),
) -> InterviewResult:
    raise NotImplementedError
