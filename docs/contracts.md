# Cross-lane contracts

Two handoffs. Everything else is internal to a lane.

Both handoffs carry `org_id`. It is not decoration: lane 2 and lane 3 write
rows whose composite foreign keys will reject them if the org does not match
their parent (D25).

## Lane 1 → Lane 2 · `InterviewPackage`

Assembled by `POST /interview/redeem`, passed into the LiveKit room as metadata.
Defined in `backend/shared/models/interview.py`.

Deliberately excludes the candidate's name and demographic detail. The
interviewer agent does not need them, and blind conduct is easier to defend than
blind conduct retrofitted after a complaint.

### Build it with `intake.packaging.build_interview_package()`

```python
from intake.packaging import build_interview_package, PackageUnavailable

package = build_interview_package(application_id, org_id, interview_id)
```

Lane 2 should not assemble this itself. It used to fetch the application,
validate `job.question_bank` into `Question` objects and format a resume summary
inline — all three are lane 1 models, so every change to them broke lane 2's
file. Behind this function they stop being lane 2's problem.

It raises `PackageUnavailable` rather than returning a package with no
questions. An interview that starts and has nothing to ask is worse for the
candidate than one that never starts.

**The questions now vary per candidate (D40).** The `InterviewPackage` shape and
the `Question` shape are both unchanged — each question still carries its
`dimensions`, and they are identical across candidates for the same competency.
What changed is where they come from: `application.questions`, generated at
invite time, with `job.question_bank` as the fallback for jobs built before the
switch. That is exactly the reason to go through this function; the fallback
lives inside it.

### Redeem order of operations

1. Hash the presented token, look up the invite
2. Reject if expired, or if it redeemed into a `COMPLETED` interview
3. If it redeemed into an `IN_PROGRESS` interview inside the rejoin window,
   reuse that interview and room — this is what survives a dropped connection
4. Otherwise create the `Interview` row and a LiveKit room
5. `build_interview_package(...)`, dispatch the agent with it as metadata
6. Mint a short-lived LiveKit access token scoped to that room and identity
7. Return the access token. Never return or log the invite token

Two tokens, different lifetimes: the **invite token** lives for days and is
single-redeem; the **LiveKit access token** lives for minutes and is minted
fresh on every join, including rejoins.

## Lane 2 → Lane 3 · `InterviewResult`

Written by the voice worker after the call, read by the leaderboard and the
recruiter chat. Defined in `backend/shared/models/scoring.py`.

`DimensionScore.evidence` is required and must be a verbatim transcript quote.
Lane 3's entire value is answering "why did it score a 3 on depth?" — without a
quote it can only paraphrase, which is the black-box behaviour we are
differentiating against.

Rubric v2 adds `AnswerScore.fixed_rubric`, containing the anchored 0-100
technical accuracy, project depth, follow-up resilience, ownership, and
consistency measurements. Lane 2 must pass the completed answer list through
`shared.interview_scoring.apply_rubric_to_result()` before persisting it. The
function, not the LLM, calculates seniority weights, caps, penalties, the final
composite, and human-review reasons.

Lane 2 then serializes the completed contract with
`shared.interview_scoring.build_interview_score_row()` before inserting or
upserting `interview_score`. This keeps indexed summary columns and the full
`result` JSON identical.

Each `question_instance` stores the scalar scoring context directly:
`question_text`, `question_type`, `competency`, `seniority`, and the three claim
flags. Its ordered resume/prior-answer claims live in `question_scoring_claim`;
its ordered answer and follow-up turns live in `question_conversation_turn`.
Lane 2 assembles those rows into Gemini user content without persisting a new
`scoring_input` JSON object.

The validated `fixed_rubric` returned by `score-answer.v2` is an in-memory
Pydantic response contract. Lane 2 flattens it into the one-to-one
`question_rubric_assessment` table: each applicable score, evidence quote,
rationale, label, model id, and prompt version has a typed column. No new
`question_instance.fixed_rubric` JSONB is written. Indexed interview aggregates
remain in `interview_score`.

After transcript segmentation, Lane 2 wraps all validated `ScoreAnswerInput`
packages in one `ScoreInterviewInput` and calls
`shared.post_call_scoring.score_interview()`. Exactly one `score-interview` call
returns every per-question assessment plus holistic explanation. Application
code verifies the complete question-id set, restores question-bank order,
attaches registry provenance, and copies factual context flags from trusted
input. Persist assessments only after the response validates; then run
deterministic aggregation.

`InterviewResult.overall` remains a derived 1-5 compatibility field. Lane 3
ranks new results by `composite_score`; it falls back to `overall` only for v1
rows that have not been re-scored.

## Changing either

Both are Pydantic models, so a change ripples to OpenAPI, the frontend's
generated types, and the Gemini response schemas at once. Say so in the group
chat before you push, and run `npm run gen:types` after.
