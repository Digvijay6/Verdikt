"""Organization resolution.

This is where "may this person touch this org's data" is decided, so it is
tested for what it *refuses* as much as what it allows.
"""

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from api import deps
from api.deps import AuthenticatedUser
from shared.models.organization import Membership, Role

ACME = "11111111-1111-1111-1111-111111111111"
GLOBEX = "22222222-2222-2222-2222-222222222222"

USER = AuthenticatedUser(id="user-1", email="rec@example.com")


def membership(org_id: str, role: Role = Role.RECRUITER) -> Membership:
    return Membership(
        id=f"m-{org_id[:4]}",
        org_id=org_id,
        user_id=USER.id,
        role=role,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def memberships(monkeypatch):
    def apply(*rows: Membership):
        monkeypatch.setattr(deps.tenancy, "memberships_for_user", lambda _uid: list(rows))

    return apply


# --- the common case ------------------------------------------------------


def test_single_membership_needs_no_header(memberships):
    """Most users belong to one org, so the UI never shows a switcher."""
    memberships(membership(ACME))
    rec = deps.current_recruiter(user=USER, x_org_id=None)
    assert rec.org_id == ACME
    assert rec.id == USER.id


def test_role_comes_from_membership_not_the_token(memberships):
    memberships(membership(ACME, Role.OWNER))
    assert deps.current_recruiter(user=USER, x_org_id=None).role is Role.OWNER


# --- refusals -------------------------------------------------------------


def test_no_membership_is_forbidden(memberships):
    """A valid login with no organization can still do nothing."""
    memberships()
    with pytest.raises(HTTPException) as exc:
        deps.current_recruiter(user=USER, x_org_id=None)
    assert exc.value.status_code == 403


def test_org_the_user_does_not_belong_to_is_forbidden(memberships):
    memberships(membership(ACME))
    with pytest.raises(HTTPException) as exc:
        deps.current_recruiter(user=USER, x_org_id=GLOBEX)
    assert exc.value.status_code == 403


def test_unknown_org_is_forbidden_not_not_found(memberships):
    """403 rather than 404 deliberately: distinguishing "no such org" from
    "not yours" would let anyone probe for which org ids exist."""
    memberships(membership(ACME))
    with pytest.raises(HTTPException) as exc:
        deps.current_recruiter(user=USER, x_org_id="99999999-9999-9999-9999-999999999999")
    assert exc.value.status_code == 403


# --- multi-org users ------------------------------------------------------


def test_multiple_memberships_require_the_header(memberships):
    """Guessing would silently write a job into the wrong client's account."""
    memberships(membership(ACME), membership(GLOBEX))
    with pytest.raises(HTTPException) as exc:
        deps.current_recruiter(user=USER, x_org_id=None)
    assert exc.value.status_code == 400


def test_multiple_memberships_honour_the_header(memberships):
    memberships(membership(ACME), membership(GLOBEX))
    assert deps.current_recruiter(user=USER, x_org_id=GLOBEX).org_id == GLOBEX
    assert deps.current_recruiter(user=USER, x_org_id=ACME).org_id == ACME
