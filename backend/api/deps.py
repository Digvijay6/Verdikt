"""Shared FastAPI dependencies.

Two distinct callers, two distinct auth paths:

  recruiters  -> Supabase Auth JWT in the Authorization header
  candidates  -> an invite token in the URL, no account, no login

Never let the candidate path reach a recruiter-scoped route. They are separate
audiences that happen to share a domain.
"""

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from shared.config import get_settings

bearer = HTTPBearer(auto_error=True)


class Recruiter(BaseModel):
    id: str
    email: str
    org_id: str | None = None


def current_recruiter(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> Recruiter:
    """Verify a Supabase Auth JWT and return the recruiter."""
    try:
        claims = jwt.decode(
            creds.credentials,
            get_settings().supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    return Recruiter(
        id=claims["sub"],
        email=claims.get("email", ""),
        org_id=(claims.get("app_metadata") or {}).get("org_id"),
    )
