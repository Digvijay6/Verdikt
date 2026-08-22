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
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from pydantic import BaseModel

from shared import tenancy
from shared.config import get_settings
from shared.models.organization import Role

bearer = HTTPBearer(auto_error=True)

ASYMMETRIC_ALGS = ("ES256", "RS256")


class AuthenticatedUser(BaseModel):
    """A verified identity, before any organization is resolved."""

    id: str
    email: str


class Recruiter(BaseModel):
    """A verified identity acting for a specific organization.

    `org_id` is not optional and does not come from the token. It is resolved
    from `membership` on every request, so revoking someone's access takes
    effect immediately rather than whenever their session next refreshes.
    """

    id: str
    email: str
    org_id: str
    role: Role


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


def current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
) -> AuthenticatedUser:
    """Verify a Supabase Auth JWT. Says who, not what they may do."""
    try:
        claims = _decode(creds.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    return AuthenticatedUser(id=claims["sub"], email=claims.get("email", ""))


def current_recruiter(
    user: AuthenticatedUser = Depends(current_user),
    x_org_id: str | None = Header(
        None,
        description=(
            "Which organization to act for. Only needed by users who belong to "
            "more than one; otherwise their single membership is used."
        ),
    ),
) -> Recruiter:
    """Resolve the organization this request acts on behalf of.

    Most users belong to exactly one organization, so the header is optional and
    the UI never has to show an org switcher. Agencies and consultants belong to
    several, and must say which — guessing on their behalf would silently write
    a job into the wrong client's account.
    """
    memberships = tenancy.memberships_for_user(user.id)

    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account does not belong to any organization.",
        )

    if x_org_id is None:
        if len(memberships) > 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "You belong to multiple organizations. "
                    "Send X-Org-Id to say which one."
                ),
            )
        membership = memberships[0]
    else:
        found = next((m for m in memberships if m.org_id == x_org_id), None)
        if found is None:
            # Deliberately 403 rather than 404: distinguishing "no such org"
            # from "not yours" would let anyone probe for which org ids exist.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to that organization.",
            )
        membership = found

    return Recruiter(
        id=user.id,
        email=user.email,
        org_id=membership.org_id,
        role=membership.role,
    )
