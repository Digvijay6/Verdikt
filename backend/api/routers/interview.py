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

from fastapi import APIRouter
from pydantic import BaseModel

from shared.models.interview import IntegrityEvent

router = APIRouter(prefix="/interview", tags=["interview"])


class RedeemRequest(BaseModel):
    token: str


class RedeemResponse(BaseModel):
    interview_id: str
    room_name: str
    livekit_url: str
    access_token: str = "Short-lived. Scoped to one room and identity."
    resuming: bool = False


@router.post("/redeem", response_model=RedeemResponse)
def redeem(body: RedeemRequest) -> RedeemResponse:
    """Public — the candidate has no account. The token is the auth."""
    raise NotImplementedError


@router.post("/events", status_code=202)
def proctor_events(events: list[IntegrityEvent]) -> None:
    """Browser telemetry from frontend/src/lib/proctor.

    Treat every field as hostile. It arrives from a page the candidate can open
    devtools on, so it is evidence for a human reviewer, never a hard gate.
    """
    raise NotImplementedError
