"""Interview invites — token minting and the candidate email.

Two tokens exist in this system and they are easy to confuse (D12):

  invite token   (here)      days,    single-redeem, in the emailed URL
  LiveKit token  (lane 2)    minutes, per-join,      never emailed

Only the *hash* of the invite token is stored. A database leak therefore does
not hand out working interview links.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import resend

from shared.config import get_settings
from shared.models.job import Job


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def mint_token() -> tuple[str, str, datetime]:
    """Returns (raw_token, token_hash, expires_at).

    The raw token is returned exactly once, goes straight into the email, and is
    never persisted or logged.
    """
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        hours=get_settings().invite_ttl_hours
    )
    return token, hash_token(token), expires_at


def invite_link(token: str) -> str:
    return f"{get_settings().app_base_url}/interview/{token}"


def _body(candidate_name: str | None, job: Job, link: str, expires_at: datetime) -> str:
    greeting = f"Hi {candidate_name}," if candidate_name else "Hi,"
    deadline = expires_at.strftime("%d %B %Y")

    # The disclosures are not boilerplate. NY AEDTA requires notice that AI is
    # being used before the interview begins, and GDPR Art. 9 requires that
    # voice recording be disclosed and consented to rather than assumed.
    return f"""{greeting}

Thanks for applying for {job.title}. We'd like to invite you to the next stage:
a short screening interview.

  {link}

A few things to know before you start:

  - The interview is conducted by an AI interviewer, not a person.
  - It is a voice conversation in your browser. You'll need a microphone.
  - Audio is recorded and analysed to produce your assessment.
  - A human reviews the outcome. No decision is made by AI alone.
  - You can request deletion of your recording at any time by replying here.

You'll be asked to confirm the above before the interview begins.

The link works until {deadline}. It takes about 20 minutes, and you can take it
whenever suits you. If your connection drops, open the same link again and
you'll rejoin where you left off.

Good luck.
"""


def send_invite_email(
    to_email: str,
    candidate_name: str | None,
    job: Job,
    token: str,
    expires_at: datetime,
) -> str:
    """Send the invite. Returns the provider message id.

    Note for local development: Resend will not deliver to arbitrary addresses
    until a sending domain is verified. Until then it only delivers to the
    account owner's own address.
    """
    cfg = get_settings()
    resend.api_key = cfg.resend_api_key
    link = invite_link(token)

    sent = resend.Emails.send(
        {
            "from": cfg.from_email,
            "to": [to_email],
            "subject": f"Your interview for {job.title}",
            "text": _body(candidate_name, job, link, expires_at),
        }
    )
    return sent.get("id", "")
