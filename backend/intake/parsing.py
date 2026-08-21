"""Resume PDF -> ParsedResume.

Gemini reads the PDF directly, so there is no parsing vendor in this stack
(D10). The prompt does the work; this module just wires it up.
"""

from __future__ import annotations

from shared.llm import Provenance, pdf_part, run
from shared.models.candidate import ParsedResume

_INSTRUCTION = (
    "Extract the structured fields from the attached resume. "
    "Compute total_years_experience from the employment dates."
)


def parse_resume(pdf_bytes: bytes) -> tuple[ParsedResume, Provenance]:
    """The PDF goes in user content, never the system prompt — it is written by
    the candidate and is therefore untrusted input."""
    return run(
        "resume-parse",
        ParsedResume,
        user_content=[pdf_part(pdf_bytes), _INSTRUCTION],
    )
