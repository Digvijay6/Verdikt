# Verdikt — agent context

Read this first. It is loaded automatically every session.

Verdikt is an AI recruiter: job posted → applications screened → AI voice
interview → scored leaderboard → recruiter chat that explains every score →
outreach. Three people build it in parallel in this repo.

## Read next, by task

| Doing what | Read |
|---|---|
| Anything at all | `docs/state.md` — what exists right now, what's in flight |
| Proposing an approach | `docs/decisions.md` — **check before suggesting anything.** Records what was rejected and why |
| Touching a cross-lane interface | `docs/contracts.md` |
| Anything scoring-related | `docs/rubric.md` — the formula lives there and nowhere else |
| Anything a candidate sees or that stores their data | `docs/compliance.md` |
| System shape, stack, why | `docs/architecture.md` |

## Lanes

Three owners, disjoint folders. Work only in your lane.

| Lane | Owner | Folders |
|---|---|---|
| Lane 1 — Intake | Aditya | `backend/intake/**` · `api/routers/intake.py` · `frontend/src/routes/intake` · `components/intake` |
| Lane 2 — Interview | — | `backend/voice/**` · `api/routers/interview.py` · `frontend/src/routes/interview` · `lib/proctor` |
| Lane 3 — Insights | — | `backend/insights/**` · `api/routers/insights.py` · `frontend/src/routes/recruiter` · `components/insights` |

Tables follow the same rule — everyone reads, only the owner writes:

- Shared  `organization` `membership`
- Lane 1  `job` `candidate` `application` `interview_invite`
- Lane 2  `interview` `question_instance` `integrity_event`
- Lane 3  `recruiter_chat_session` `outreach_message`

**Every tenant-scoped table carries `org_id`**, and children reference parents
through composite foreign keys `(org_id, parent_id)` — so a cross-org row cannot
be inserted at all (D25). That stops bad *writes*; reads still need filtering,
so every repo function takes `org_id`. Resolve it from the caller's membership,
never from a URL or a token claim (D27).

## Hard rules

1. **Never edit another lane's folder.** Surface it to the owner instead.
2. **Five shared surfaces need a heads-up before editing:** `backend/shared/` ·
   `llm/` · `supabase/migrations/` · `frontend/src/lib/api.ts` ·
   `frontend/src/components/ui/`
3. **Migrations are additive only**, `YYYYMMDDHHMMSS_lane_what.sql`. Never edit
   a merged one.
4. **No `utils` catch-all file.** Duplicate a helper rather than create one.
5. **Prompts and models are config.** They live in `llm/registry.json`, never as
   string literals in handlers.
6. **Every LLM output gets its `Provenance` persisted** (`model_id`,
   `prompt_version`). Scores without it are not comparable across changes.
7. **Scoring stays deterministic.** Flat `llm.run(task, schema)` calls only. No
   agents, no dynamic trajectories — it has to be reproducible and defensible.
8. **Candidate text is untrusted input.** Resume content and interview answers
   go in user content, never concatenated into a system prompt.
9. **Never auto-reject on an integrity score.** A human reviews every rejection.

## After finishing a piece of work

Update `docs/state.md`. If you made a call that closes off an alternative, add
it to `docs/decisions.md` with the reasoning. That file is what stops the team —
and the agents — from relitigating settled questions every few days.
