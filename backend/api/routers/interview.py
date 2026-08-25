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
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, status
from pydantic import BaseModel

from shared.config import get_settings
from shared.db import db
from shared.llm import task_config
from shared.models.interview import IntegrityEvent, InterviewStatus

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


async def _create_livekit_room(room_name: str, metadata: str) -> None:
    """Create a LiveKit room with the InterviewPackage as metadata."""
    from livekit import api

    lk_api = api.LiveKitAPI(
        url=get_settings().livekit_url,
        api_key=get_settings().livekit_api_key,
        api_secret=get_settings().livekit_api_secret,
    )

    await lk_api.room.create_room(
        api.CreateRoomRequest(
            name=room_name,
            metadata=metadata,
        ),
    )
    await lk_api.aclose()


async def _delete_livekit_room(room_name: str) -> None:
    """Delete the media room so its worker shutdown callback runs immediately."""
    from livekit import api

    lk_api = api.LiveKitAPI(
        url=get_settings().livekit_url,
        api_key=get_settings().livekit_api_key,
        api_secret=get_settings().livekit_api_secret,
    )
    try:
        await lk_api.room.delete_room(api.DeleteRoomRequest(room=room_name))
    finally:
        await lk_api.aclose()


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


class InterviewStatusResponse(BaseModel):
    status: InterviewStatus


# --- Endpoints ------------------------------------------------------------


@router.post("/redeem", response_model=RedeemResponse)
async def redeem(body: RedeemRequest) -> RedeemResponse:
    """Public — the candidate has no account. The token is the auth.

    Order of operations (see module docstring). Never return or log the
    invite token — only its hash.
    """
    supabase = db()
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()

    # 1. Look up the invite by token hash
    invite_result = supabase.table("interview_invite").select(
        "*"
    ).eq("token_hash", token_hash).limit(1).execute()

    if not invite_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid invite token",
        )

    invite = invite_result.data[0]

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
        interview_result = (
            supabase.table("interview")
            .select("*")
            .eq("org_id", invite["org_id"])
            .eq("id", interview_id)
            .single()
            .execute()
        )
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
                    }).eq("org_id", invite["org_id"]).eq("id", interview_id).execute()
                    raise HTTPException(
                        status_code=status.HTTP_410_GONE,
                        detail="Rejoin window expired",
                    )
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="Interview already ended",
            )

    # 4. Create the Interview row and LiveKit room
    interview_id = str(uuid.uuid4())
    room_name = f"interview_{interview_id[:8]}"

    # Fetch the invite's org_id and application_id
    org_id = invite["org_id"]
    application_id = invite["application_id"]

    # Build the InterviewPackage via Lane 1's packaging function.
    # This handles per-candidate questions, resume summary, and rubric version
    # — all lane 1 models that should not be inline in lane 2.
    from intake.packaging import PackageUnavailable, build_interview_package

    try:
        package = build_interview_package(application_id, org_id, interview_id)
    except PackageUnavailable as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e

    # Create the LiveKit room with the package as metadata
    await _create_livekit_room(
        room_name=room_name,
        metadata=package.model_dump_json(),
    )

    # Create the Interview row
    now_iso = datetime.now(UTC).isoformat()
    interviewer_config = task_config("interviewer-system")
    supabase.table("interview").insert({
        "id": interview_id,
        "org_id": org_id,
        "application_id": application_id,
        "job_id": package.job_id,
        "status": "in_progress",
        "room_name": room_name,
        "seniority": package.seniority,
        "started_at": now_iso,
        "model_id": interviewer_config.model,
        "prompt_version": interviewer_config.version,
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
        org_id=org_id,
        room_name=room_name,
        livekit_url=get_settings().livekit_url,
        access_token=access_token,
        resuming=False,
    )


@router.post("/status", response_model=InterviewStatusResponse)
def interview_status(body: RedeemRequest) -> InterviewStatusResponse:
    """Return processing state to the candidate authenticated by their invite token."""
    supabase = db()
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    invite_result = (
        supabase.table("interview_invite")
        .select("org_id,interview_id")
        .eq("token_hash", token_hash)
        .limit(1)
        .execute()
    )
    if not invite_result.data or not invite_result.data[0].get("interview_id"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interview not found",
        )

    invite = invite_result.data[0]
    interview_result = (
        supabase.table("interview")
        .select("status")
        .eq("org_id", invite["org_id"])
        .eq("id", invite["interview_id"])
        .limit(1)
        .execute()
    )
    if not interview_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interview not found",
        )
    return InterviewStatusResponse(status=interview_result.data[0]["status"])


@router.post("/end", status_code=status.HTTP_202_ACCEPTED)
async def end_interview(token: Annotated[str, Form()]) -> dict[str, str]:
    """End the token holder's media room; the worker persists the final state."""
    supabase = db()
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    invite_result = (
        supabase.table("interview_invite")
        .select("org_id,interview_id")
        .eq("token_hash", token_hash)
        .limit(1)
        .execute()
    )
    if not invite_result.data or not invite_result.data[0].get("interview_id"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interview not found",
        )

    invite = invite_result.data[0]
    interview_result = (
        supabase.table("interview")
        .select("room_name,status")
        .eq("org_id", invite["org_id"])
        .eq("id", invite["interview_id"])
        .limit(1)
        .execute()
    )
    if not interview_result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interview not found",
        )

    interview = interview_result.data[0]
    if interview["status"] == InterviewStatus.IN_PROGRESS and interview.get("room_name"):
        supabase.table("interview").update({
            "ended_at": datetime.now(UTC).isoformat(),
        }).eq("org_id", invite["org_id"]).eq("id", invite["interview_id"]).execute()
        await _delete_livekit_room(interview["room_name"])
    return {"status": "ending"}


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
def proctor_events(events: list[IntegrityEvent]) -> dict[str, str]:
    """Browser telemetry from frontend/src/lib/proctor.

    Treat every field as hostile. It arrives from a page the candidate can open
    devtools on, so it is evidence for a human reviewer, never a hard gate.
    """
    supabase = db()

    for event in events:
        try:
            supabase.table("integrity_event").insert({
                "id": str(uuid.uuid4()),
                "org_id": event.org_id,
                "interview_id": event.interview_id,
                "type": event.type.value,
                "severity": event.severity,
                "at_ms": int(event.at_ms) if event.at_ms < 2147483647 else int(event.at_ms / 1000),
                "detail": json.dumps(event.detail),
            }).execute()
        except Exception:
            pass

    return {"status": "accepted"}
