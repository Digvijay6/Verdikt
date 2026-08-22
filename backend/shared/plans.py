"""Plan limits.

Kept in config rather than the database so changing a tier applies to every
organization on it immediately, instead of requiring an UPDATE across every row
and hoping none were missed. Per-org overrides live on the `organization` row
for the cases that always come up — enterprise deals, or bumping a customer
who is mid-evaluation.

Nothing enforces these yet. They are recorded so the shape is right when
billing arrives.
"""

from dataclasses import dataclass

from .models.organization import Organization, Plan


@dataclass(frozen=True)
class PlanLimits:
    max_concurrent_interviews: int
    monthly_interview_limit: int


# Concurrency protects infrastructure; monthly volume protects margin. They are
# not the same lever: two orgs running 5 interviews at once all day cost far
# more than one org running 50 at once for ten minutes, because LiveKit and
# Gemini bill by the minute rather than by the peak.
PLAN_LIMITS: dict[Plan, PlanLimits] = {
    Plan.FREE: PlanLimits(max_concurrent_interviews=2, monthly_interview_limit=25),
    Plan.PRO: PlanLimits(max_concurrent_interviews=10, monthly_interview_limit=500),
    Plan.ENTERPRISE: PlanLimits(
        max_concurrent_interviews=50, monthly_interview_limit=10_000
    ),
}


def concurrency_limit(org: Organization) -> int:
    return (
        org.max_concurrent_interviews
        if org.max_concurrent_interviews is not None
        else PLAN_LIMITS[org.plan].max_concurrent_interviews
    )


def monthly_limit(org: Organization) -> int:
    return (
        org.monthly_interview_limit
        if org.monthly_interview_limit is not None
        else PLAN_LIMITS[org.plan].monthly_interview_limit
    )
