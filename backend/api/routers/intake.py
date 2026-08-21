"""LANE 1 — Aditya. Application intake through interview invite.

Flow:
  POST /intake/applications      candidate applies (public)
    -> store resume in Supabase Storage
    -> llm.run("resume-parse")   Gemini reads the PDF natively, no parser vendor
    -> hard checks               deterministic, no LLM
    -> llm.run("screen-application")
    -> accept: mint invite token, email link via Resend
       reject / review: write decision, no email

  GET  /intake/jobs              recruiter list
  POST /intake/jobs              create job -> llm.run("jd-to-rubric") builds
                                 the question bank lane 2 will conduct
  GET  /intake/applications      recruiter review queue
"""

from fastapi import APIRouter, Depends

from shared.models.candidate import Application

from ..deps import Recruiter, current_recruiter

router = APIRouter(prefix="/intake", tags=["intake"])


@router.get("/applications", response_model=list[Application])
def list_applications(
    job_id: str,
    recruiter: Recruiter = Depends(current_recruiter),
) -> list[Application]:
    raise NotImplementedError
