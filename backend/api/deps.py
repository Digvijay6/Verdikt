"""Shared FastAPI dependencies.

Two distinct callers, two distinct auth paths:

  recruiters  -> Supabase Auth JWT in the Authorization header
  candidates  -> an invite token in the URL, no account, no login

Never let the candidate path reach a recruiter-scoped route. They are separate
audiences that happen to share a domain.

## On JWT verification

Supabase issues session tokens two ways:

  ES256/RS256  asymmetric, verified against the project's public JWKS. This is
               what new projects use and what Supabase recommends.
  HS256        the legacy shared JWT secret. Still supported, no longer
               recommended, and being phased out.

Both are handled. Which one a project uses depends on when it was created and
whether its keys have been migrated, and getting it wrong fails on every single
request — so this does not assume.
"""

from __future__ import annotations

from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from pydantic import BaseModel

from shared.config import get_settings

bearer = HTTPBearer(auto_error=True)

ASYMMETRIC_ALGS = ("ES256", "RS256")


class Recruiter(BaseModel):
    id: str
    email: str
    org_id: str | None = None


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    """Public keys for verifying asymmetric tokens.

    PyJWKClient caches the key set and refetches on an unknown `kid`, which is
    what makes Supabase's zero-downtime key rotation work without a redeploy.
    """
    url = get_settings().supabase_url.rstrip("/")
    return PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json")


def _decode(token: str) -> dict:
    """Verify a Supabase session token, asymmetric first.

    The algorithm comes from the token header, which is normally where
    algorithm-confusion attacks start. It is safe here because each branch is
    pinned to a disjoint algorithm list and a distinct key: an attacker cannot
    get a token verified against the wrong key type by relabelling it, and the
    HS256 branch is unreachable unless a shared secret is actually configured.
    """
    alg = jwt.get_unverified_header(token).get("alg")

    if alg in ASYMMETRIC_ALGS:
        key = _jwks_client().get_signing_key_from_jwt(token).key
        return jwt.decode(
            token, key, algorithms=list(ASYMMETRIC_ALGS), audience="authenticated"
        )

    if alg == "HS256":
        secret = get_settings().supabase_jwt_secret
        if not secret:
            raise jwt.InvalidTokenError(
                "Token is HS256 but no SUPABASE_JWT_SECRET is configured"
            )
        return jwt.decode(
            token, secret, algorithms=["HS256"], audience="authenticated"
        )

    raise jwt.InvalidTokenError(f"Unsupported token algorithm: {alg}")


def current_recruiter(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> Recruiter:
    """Verify a Supabase Auth JWT and return the recruiter."""
    try:
        claims = _decode(creds.credentials)
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
