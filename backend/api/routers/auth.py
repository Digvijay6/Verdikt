"""LANE 1 — signup and organization onboarding.

Passwords never reach this server. The browser calls Supabase Auth directly
(`supabase.auth.signUp` / `signInWithPassword`), Supabase issues a JWT, and
these endpoints only ever see that verified token. Nothing here can leak a
credential because nothing here handles one.

The endpoints below depend on `current_user`, not `current_recruiter` — a
person who has just signed up has no membership yet, so requiring one would
make it impossible to ever create the first organization.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from shared.db import db
from shared.models.organization import Membership, Organization, Role
from shared.tenancy import memberships_for_user

from ..deps import AuthenticatedUser, current_user

router = APIRouter(prefix="/auth", tags=["auth"])

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESERVED = {"api", "app", "admin", "www", "auth", "j", "apply", "interview",
            "sitemap", "robots", "static", "assets", "health", "docs"}


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    slug: str = Field(
        min_length=2,
        max_length=40,
        description="Lowercase letters, numbers and hyphens. Used in URLs.",
    )


class Me(BaseModel):
    """Everything the client needs to decide what to render.

    `organizations` being empty is the signal to show onboarding rather than
    the dashboard — it is not an error state.
    """

    user: AuthenticatedUser
    organizations: list[Organization] = []
    memberships: list[Membership] = []


@router.get("/me", response_model=Me)
def me(user: AuthenticatedUser = Depends(current_user)) -> Me:
    memberships = memberships_for_user(user.id)
    if not memberships:
        return Me(user=user)

    rows = (
        db()
        .table("organization")
        .select("*")
        .in_("id", [m.org_id for m in memberships])
        .execute()
        .data
    )
    return Me(
        user=user,
        organizations=[Organization.model_validate(r) for r in rows],
        memberships=memberships,
    )


@router.post(
    "/organizations",
    response_model=Organization,
    status_code=status.HTTP_201_CREATED,
)
def create_organization(
    payload: OrganizationCreate,
    user: AuthenticatedUser = Depends(current_user),
) -> Organization:
    """Create an organization and make the caller its owner.

    Deliberately allows a user to belong to several: agencies and consultants
    work across companies, and the UI hides that from anyone with only one.
    """
    slug = payload.slug.strip().lower()
    if not SLUG.match(slug):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Slug must be lowercase letters, numbers and hyphens.",
        )
    if slug in RESERVED:
        # These collide with real paths — an org at /apply would shadow the
        # application form.
        raise HTTPException(status.HTTP_409_CONFLICT, "That name is reserved.")

    taken = db().table("organization").select("id").eq("slug", slug).execute()
    if taken.data:
        raise HTTPException(status.HTTP_409_CONFLICT, "That slug is already taken.")

    org = (
        db()
        .table("organization")
        .insert({"name": payload.name.strip(), "slug": slug, "plan": "free"})
        .execute()
        .data[0]
    )

    # If this insert fails the organization is orphaned and unreachable, since
    # every route resolves access through membership. Cheaper to delete it than
    # to leave a row nobody can ever reach.
    try:
        db().table("membership").insert(
            {"org_id": org["id"], "user_id": user.id, "role": Role.OWNER.value}
        ).execute()
    except Exception:
        db().table("organization").delete().eq("id", org["id"]).execute()
        raise

    return Organization.model_validate(org)
