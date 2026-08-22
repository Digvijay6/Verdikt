"""Resolving which organization a request acts on behalf of.

Membership is read from the database per request rather than baked into the
JWT. A token claim goes stale the moment someone's access changes — revoking
access should take effect immediately, not whenever their session next
refreshes.
"""

from __future__ import annotations

from .db import db
from .models.organization import Membership, Organization


def memberships_for_user(user_id: str) -> list[Membership]:
    res = db().table("membership").select("*").eq("user_id", user_id).execute()
    return [Membership.model_validate(r) for r in res.data]


def membership_in(user_id: str, org_id: str) -> Membership | None:
    """Authoritative check that a user may act for an organization.

    Every tenant-scoped request passes through here. It is the single place
    where "may this person touch this org's data" is decided.
    """
    res = (
        db()
        .table("membership")
        .select("*")
        .eq("user_id", user_id)
        .eq("org_id", org_id)
        .execute()
    )
    return Membership.model_validate(res.data[0]) if res.data else None


def get_organization(org_id: str) -> Organization | None:
    res = db().table("organization").select("*").eq("id", org_id).execute()
    return Organization.model_validate(res.data[0]) if res.data else None
