"""Extracting hard requirements from a job description.

Optional — a recruiter can fill in the `ScreeningProfile` by hand instead. When
Gemini does it, the result is recorded with its provenance and shown on the job
page, and screen-rejected candidates stay visible and reversible. That is the
safety valve for the fact that this output automatically rejects people.
"""

from __future__ import annotations

from shared.llm import Provenance, run
from shared.models.job import ScreeningProfile


def extract_screening_profile(
    jd_text: str, title: str, seniority: str
) -> tuple[ScreeningProfile, Provenance]:
    """The JD is written by the recruiter, so it is trusted input.

    That distinction matters: it is why the JD may go in the prompt at all,
    whereas résumé text never can.
    """
    return run(
        "jd-to-requirements",
        ScreeningProfile,
        user_content=(
            f"Role: {title}\nSeniority: {seniority}\n\nJob description:\n{jd_text}"
        ),
    )
