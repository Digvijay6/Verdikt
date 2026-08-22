"""Tenancy — the company using Verdikt, and who may act on its behalf.

Every other table hangs off `organization`. Isolation is enforced by composite
foreign keys in the database, not by remembering to filter, so a row belonging
to the wrong org cannot be inserted at all.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Plan(StrEnum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class Role(StrEnum):
    OWNER = "owner"
    RECRUITER = "recruiter"


class Organization(BaseModel):
    id: str
    name: str
    slug: str

    plan: Plan = Plan.FREE

    # None means "use the plan default" (see shared/plans.py). Changing a tier's
    # limit is then a config edit rather than an UPDATE across every row on that
    # tier; these columns exist for the exceptions — enterprise deals, or
    # temporarily bumping a customer who is evaluating.
    max_concurrent_interviews: int | None = Field(
        None, description="Protects infrastructure. None = plan default."
    )
    monthly_interview_limit: int | None = Field(
        None, description="The commercial lever. None = plan default."
    )

    created_at: datetime


class Membership(BaseModel):
    """A user's access to one organization.

    A join table rather than `user.org_id` because recruiting agencies and
    consultants work across companies. The UI can still assume a single org and
    skip the switcher when someone has exactly one membership.
    """

    id: str
    org_id: str
    user_id: str
    role: Role = Role.RECRUITER
    created_at: datetime


class OrganizationCreate(BaseModel):
    name: str
    slug: str
