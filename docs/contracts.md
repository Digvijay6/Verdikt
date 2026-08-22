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

### Redeem order of operations

1. Hash the presented token, look up the invite
2. Reject if expired, or if it redeemed into a `COMPLETED` interview
3. If it redeemed into an `IN_PROGRESS` interview inside the rejoin window,
   reuse that interview and room — this is what survives a dropped connection
4. Otherwise create the `Interview` row and a LiveKit room
5. Assemble the `InterviewPackage`, dispatch the agent with it as metadata
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

## Changing either

Both are Pydantic models, so a change ripples to OpenAPI, the frontend's
generated types, and the Gemini response schemas at once. Say so in the group
chat before you push, and run `npm run gen:types` after.
