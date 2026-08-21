"""Deterministic screening gate. No model runs here.

Two reasons this is plain Python rather than part of the LLM screen:

  1. It is free and instant, so the model only ever sees survivors (D18).
  2. It rejects people. A rule you can read, test, and point at in a dispute is
     the only defensible way to do that.

Design bias throughout: **a false reject is invisible and unappealable.** The
candidate never learns why, so there is no correction mechanism. Every judgement
call below therefore leans toward letting someone through to the LLM screen,
which sees the whole resume and can recommend `review`.
"""

from __future__ import annotations

import re

from shared.models.candidate import HardCheckResult, ParsedResume
from shared.models.job import ScreeningProfile


def _normalize(text: str) -> str:
    """Lowercase and collapse punctuation so 'Node.js' and 'nodejs' compare equal."""
    return re.sub(r"[^a-z0-9+#]+", "", text.lower())


def _resume_corpus(resume: ParsedResume) -> str:
    """Everything a skill might plausibly be mentioned in.

    Parsers routinely miss skills that appear only in prose ("used React
    heavily") rather than in a skills list. Searching the employment summaries
    too is the single biggest reduction in false rejects available here.
    """
    parts = list(resume.skills)
    for job in resume.employment:
        parts.extend([job.title, job.summary or ""])
    for edu in resume.education:
        parts.append(edu.field_of_study or "")
    return " ".join(p for p in parts if p)


def _mentions_skill(skill: str, resume: ParsedResume) -> bool:
    """True if the skill appears in the skills list or anywhere in the prose.

    Word-boundary matched on the raw text so 'java' does not match 'javascript',
    then normalized-exact matched against the skills list so 'Node.js' matches
    'nodejs'. Deliberately not fuzzy: fuzzy matching on a gate that rejects
    people trades a visible problem for an invisible one.
    """
    target = _normalize(skill)
    if any(_normalize(s) == target for s in resume.skills):
        return True

    corpus = _resume_corpus(resume)
    return re.search(rf"\b{re.escape(skill)}\b", corpus, re.IGNORECASE) is not None


def _location_ok(resume: ParsedResume, profile: ScreeningProfile) -> bool:
    if profile.remote_ok or not profile.locations:
        return True
    if not resume.location:
        # Unknown location is not a rejection. The parser may simply have missed
        # it, and guessing against the candidate is exactly the failure mode this
        # module is written to avoid.
        return True
    candidate_loc = _normalize(resume.location)
    return any(_normalize(loc) in candidate_loc for loc in profile.locations)


def run_hard_checks(
    resume: ParsedResume, profile: ScreeningProfile
) -> list[HardCheckResult]:
    """Run every configured check. Always returns all results, pass or fail, so
    the recruiter can see the full picture rather than just the first failure."""
    results: list[HardCheckResult] = []

    if profile.min_years_experience is not None:
        actual = resume.total_years_experience
        if actual is None:
            # Could not compute it. Not the candidate's fault — pass and let the
            # LLM screen weigh in.
            results.append(
                HardCheckResult(
                    check="min_years_experience",
                    passed=True,
                    detail=(
                        f"Requires {profile.min_years_experience}y; could not compute "
                        "from resume, passed to LLM screen rather than rejected"
                    ),
                )
            )
        else:
            ok = actual >= profile.min_years_experience
            results.append(
                HardCheckResult(
                    check="min_years_experience",
                    passed=ok,
                    detail=f"Requires {profile.min_years_experience}y, found {actual}y",
                )
            )

    for skill in profile.required_skills:
        found = _mentions_skill(skill, resume)
        results.append(
            HardCheckResult(
                check=f"required_skill:{skill}",
                passed=found,
                detail=("Found in resume" if found else "Not found in resume"),
            )
        )

    if profile.locations and not profile.remote_ok:
        ok = _location_ok(resume, profile)
        results.append(
            HardCheckResult(
                check="location",
                passed=ok,
                detail=(
                    f"Requires one of {profile.locations}; "
                    f"candidate: {resume.location or 'unknown'}"
                ),
            )
        )

    if profile.work_authorization:
        # Nothing in a resume reliably states work authorization, and inferring
        # it from nationality or location markers is both unreliable and legally
        # hazardous. Recorded as a check for the recruiter, never auto-failed.
        results.append(
            HardCheckResult(
                check="work_authorization",
                passed=True,
                detail=(
                    f"Requires {profile.work_authorization}; not inferable from a "
                    "resume — confirm with the candidate"
                ),
            )
        )

    return results


def passed(results: list[HardCheckResult]) -> bool:
    return all(r.passed for r in results)


def failures(results: list[HardCheckResult]) -> list[HardCheckResult]:
    return [r for r in results if not r.passed]
