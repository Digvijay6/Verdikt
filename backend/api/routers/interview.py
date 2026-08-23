"""LANE 2 — the interview surface.

The redeem endpoint is the seam between lane 1 and lane 2. Order matters:

  1. hash the presented token, look up the invite
  2. reject if expired, or if redeemed into a COMPLETED interview
  3. if redeemed into an IN_PROGRESS interview inside the rejoin window,
     reuse that interview and room  <- this is what survives a dropped wifi
  4. otherwise create the Interview row and a LiveKit room
  5. assemble the InterviewPackage and dispatch the agent with it as metadata
  6. mint a short-lived LiveKit access token scoped to that room and identity
  7. return the access token — never the invite token

The worker is not an HTTP service. It receives everything through room
metadata and writes results straight to Supabase.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from shared.config import get_settings
from shared.db import db
from shared.models.interview import IntegrityEvent, InterviewPackage
from shared.models.job import Question

router = APIRouter(prefix="/interview", tags=["interview"])


# --- LiveKit Server API client -------------------------------------------


def _livekit_token(room_name: str, identity: str, ttl_minutes: int = 15) -> str:
    """Mint a short-lived LiveKit access token scoped to one room."""
    from livekit import api

    token = api.AccessToken(
        api_key=get_settings().livekit_api_key,
        api_secret=get_settings().livekit_api_secret,
    ).with_identity(identity).with_name("candidate").with_grants(
        api.VideoGrants(
            room_join=True,
            room=room_name,
            can_publish=True,
            can_subscribe=True,
        ),
    )
    return token.to_jwt()


def _create_livekit_room(room_name: str, metadata: str) -> None:
    """Create a LiveKit room with the InterviewPackage as metadata."""
    from livekit import api

    lk_api = api.LiveKitAPI(
        url=get_settings().livekit_url,
        api_key=get_settings().livekit_api_key,
        api_secret=get_settings().livekit_api_secret,
    )

    import asyncio

    async def _create():
        await lk_api.room.create_room(
            api.CreateRoomRequest(
                name=room_name,
                metadata=metadata,
            ),
        )

    asyncio.run(_create())


# --- Request / response models -------------------------------------------


class RedeemRequest(BaseModel):
    token: str


class RedeemResponse(BaseModel):
    interview_id: str
    org_id: str
    room_name: str
    livekit_url: str
    access_token: str
    resuming: bool = False


# --- Endpoints ------------------------------------------------------------


@router.post("/redeem", response_model=RedeemResponse)
def redeem(body: RedeemRequest) -> RedeemResponse:
    """Public — the candidate has no account. The token is the auth.

    Order of operations (see module docstring). Never return or log the
    invite token — only its hash.
    """
    supabase = db()
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()

    # 1. Look up the invite by token hash
    invite_result = supabase.table("interview_invite").select(
        "*"
    ).eq("token_hash", token_hash).single().execute()

    if not invite_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid invite token",
        )

    invite = invite_result.data

    # 2. Reject if expired
    expires_at = datetime.fromisoformat(invite["expires_at"])
    if expires_at < datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Invite has expired",
        )

    # 3. If already redeemed — check for rejoin
    interview_id = invite.get("interview_id")
    if interview_id:
        interview_result = supabase.table("interview").select(
            "*"
        ).eq("id", interview_id).single().execute()
        if interview_result.data:
            interview = interview_result.data
            if interview["status"] == "completed":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Interview already completed",
                )
            if interview["status"] == "in_progress":
                # Check rejoin window
                started_at = datetime.fromisoformat(interview["started_at"])
                rejoin_window = get_settings().interview_rejoin_window_minutes
                if (datetime.now(UTC) - started_at).total_seconds() / 60 < rejoin_window:
                    # Rejoin — mint a fresh token
                    access_token = _livekit_token(
                        room_name=interview["room_name"],
                        identity=f"candidate_{interview['id']}",
                    )
                    return RedeemResponse(
                        interview_id=interview_id,
                        org_id=interview.get("org_id", ""),
                        room_name=interview["room_name"],
                        livekit_url=get_settings().livekit_url,
                        access_token=access_token,
                        resuming=True,
                    )
                else:
                    # Rejoin window expired — mark as abandoned
                    supabase.table("interview").update({
                        "status": "abandoned",
                        "ended_at": datetime.now(UTC).isoformat(),
                    }).eq("id", interview_id).execute()
                    raise HTTPException(
                        status_code=status.HTTP_410_GONE,
                        detail="Rejoin window expired",
                    )

    # 4. Create the Interview row and LiveKit room
    interview_id = str(uuid.uuid4())
    room_name = f"interview_{interview_id[:8]}"

    # Fetch the application to get job_id and resume info
    application_result = supabase.table("application").select(
        "*, job(*)"
    ).eq("id", invite["application_id"]).single().execute()

    if not application_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )

    application = application_result.data
    job = application.get("job", {})

    # Load the question bank from the job (generated by Lane 1)
    question_bank_raw = job.get("question_bank") or []
    questions = [Question.model_validate(q) for q in question_bank_raw]

    # Load the parsed resume highlights if present
    parsed_resume_data = application.get("parsed_resume")
    resume_summary = ""
    resume_highlights = None
    if parsed_resume_data:
        from shared.models.candidate import ParsedResume
        resume_highlights = ParsedResume.model_validate(parsed_resume_data)
        resume_summary = (
            f"{resume_highlights.full_name or 'Candidate'} — "
            f"{resume_highlights.total_years_experience or 0} years. "
            f"Skills: {', '.join(resume_highlights.skills[:10])}. "
            f"Recent: "
            f"{resume_highlights.employment[0].title if resume_highlights.employment else 'N/A'}"
            if resume_highlights.employment or resume_highlights.skills
            else ""
        )

    # Assemble the InterviewPackage (Lane 1 -> Lane 2 handoff)
    package = InterviewPackage(
        interview_id=interview_id,
        org_id=job["org_id"],
        job_id=job["id"],
        job_title=job.get("title", ""),
        seniority=job.get("seniority", "mid"),
        questions=questions,
        resume_summary=resume_summary,
        resume_highlights=resume_highlights,
        rubric_version=job.get("rubric_version", "v1"),
        language="en",
    )

    # Create the LiveKit room with the package as metadata
    _create_livekit_room(
        room_name=room_name,
        metadata=package.model_dump_json(),
    )

    # Create the Interview row
    now_iso = datetime.now(UTC).isoformat()
    supabase.table("interview").insert({
        "id": interview_id,
        "org_id": job["org_id"],
        "application_id": invite["application_id"],
        "job_id": job["id"],
        "status": "in_progress",
        "room_name": room_name,
        "seniority": job.get("seniority", "mid"),
        "started_at": now_iso,
    }).execute()

    # Mark the invite as redeemed
    supabase.table("interview_invite").update({
        "redeemed_at": now_iso,
        "interview_id": interview_id,
    }).eq("id", invite["id"]).execute()

    # 6. Mint the access token
    access_token = _livekit_token(
        room_name=room_name,
        identity=f"candidate_{interview_id}",
    )

    return RedeemResponse(
        interview_id=interview_id,
        org_id=job["org_id"],
        room_name=room_name,
        livekit_url=get_settings().livekit_url,
        access_token=access_token,
        resuming=False,
    )


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
def proctor_events(events: list[IntegrityEvent]) -> dict[str, str]:
    """Browser telemetry from frontend/src/lib/proctor.

    Treat every field as hostile. It arrives from a page the candidate can open
    devtools on, so it is evidence for a human reviewer, never a hard gate.
    """
    supabase = db()

    for event in events:
        supabase.table("integrity_event").insert({
            "id": str(uuid.uuid4()),
            "org_id": event.org_id,
            "interview_id": event.interview_id,
            "type": event.type.value,
            "severity": event.severity,
            "at_ms": event.at_ms,
            "detail": json.dumps(event.detail),
        }).execute()

    return {"status": "accepted"}