"""Resume PDF -> ParsedResume.

Gemini reads the PDF directly, so there is no parsing vendor in this stack
(D10). The prompt does the work; this module wires it up and supplies the one
thing the model cannot know.
"""

from __future__ import annotations

from datetime import date

from shared.llm import Provenance, pdf_part, run
from shared.models.candidate import ParsedResume


def _instruction(today: date) -> str:
    """Anchor the model to a real date.

    A language model has no idea what day it is. Asked to interpret "Present",
    it places the present somewhere near its training cutoff — which
    undercounts every current role by however long ago that was, silently and
    plausibly. On a job with a minimum-years gate, that is the difference
    between an interview and a rejection nobody ever explains.

    Observed before this fix: a resume running to "Present" was scored at 6.8
    years when the true figure was 8.1, because the model assumed "now" was
    roughly eighteen months earlier than it was.
    """
    return (
        f"Today's date is {today.isoformat()}.\n"
        f"Wherever the resume says Present, Current, Now, or leaves a date "
        f"range open, treat it as ending {today.isoformat()}.\n\n"
        "Extract the structured fields from the attached resume, and compute "
        "total_years_experience from the employment dates."
    )


def parse_resume(
    pdf_bytes: bytes, today: date | None = None
) -> tuple[ParsedResume, Provenance]:
    """The PDF goes in user content, never the system prompt — it is written by
    the candidate and is therefore untrusted input.

    `today` is injectable so tests can pin it; a test that depends on the real
    clock starts failing on its own months later.
    """
    return run(
        "resume-parse",
        ParsedResume,
        user_content=[pdf_part(pdf_bytes), _instruction(today or date.today())],
    )
