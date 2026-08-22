"""Create a development organization, recruiter, and membership.

There is no signup flow yet, so every recruiter endpoint returns 403 until an
organization and a membership exist. This makes one of each and prints a JWT you
can paste into /docs.

    python -m scripts.seed_dev

Idempotent: re-running reuses whatever is already there rather than piling up
duplicate orgs.

Development only. It uses the service key to create an auth user directly,
which is exactly what a real signup flow must not do.
"""

from __future__ import annotations

import sys

from supabase import create_client

from shared.config import get_settings
from shared.db import db

ORG_NAME = "Acme Corp"
ORG_SLUG = "acme"
EMAIL = "recruiter@example.com"
PASSWORD = "verdikt-dev-password"


def ensure_org() -> str:
    existing = db().table("organization").select("*").eq("slug", ORG_SLUG).execute()
    if existing.data:
        print(f"  organization  {ORG_SLUG} (existing)")
        return existing.data[0]["id"]

    row = (
        db()
        .table("organization")
        .insert({"name": ORG_NAME, "slug": ORG_SLUG, "plan": "free"})
        .execute()
        .data[0]
    )
    print(f"  organization  {ORG_SLUG} (created)")
    return row["id"]


def ensure_user() -> str:
    """Find or create the recruiter in Supabase Auth."""
    users = db().auth.admin.list_users()
    for u in users:
        if (u.email or "").lower() == EMAIL:
            print(f"  auth user     {EMAIL} (existing)")
            return u.id

    created = db().auth.admin.create_user(
        {"email": EMAIL, "password": PASSWORD, "email_confirm": True}
    )
    print(f"  auth user     {EMAIL} (created)")
    return created.user.id


def ensure_membership(org_id: str, user_id: str) -> None:
    existing = (
        db()
        .table("membership")
        .select("*")
        .eq("org_id", org_id)
        .eq("user_id", user_id)
        .execute()
    )
    if existing.data:
        print("  membership    owner (existing)")
        return
    db().table("membership").insert(
        {"org_id": org_id, "user_id": user_id, "role": "owner"}
    ).execute()
    print("  membership    owner (created)")


def sign_in() -> str:
    """Sign in through the public client, exactly as the browser would.

    Deliberately not minted with the service key — this proves the real login
    path works, including the ES256 verification in api/deps.py.
    """
    cfg = get_settings()
    anon = cfg.supabase_anon_key
    if not anon:
        sys.exit(
            "SUPABASE_ANON_KEY is not set in backend/.env.\n"
            "Copy the value of VITE_SUPABASE_ANON_KEY into it."
        )
    public = create_client(cfg.supabase_url, anon)
    session = public.auth.sign_in_with_password(
        {"email": EMAIL, "password": PASSWORD}
    )
    return session.session.access_token


def main() -> None:
    print("seeding development tenant\n")
    org_id = ensure_org()
    user_id = ensure_user()
    ensure_membership(org_id, user_id)
    token = sign_in()

    print(f"\n  org_id        {org_id}")
    print(f"  login         {EMAIL} / {PASSWORD}")
    print("\naccess token (expires in about an hour):\n")
    print(token)
    print(
        "\nIn http://localhost:8000/docs click Authorize and paste the token.\n"
        "X-Org-Id is not needed — this user belongs to exactly one organization."
    )


if __name__ == "__main__":
    main()
