# Current state

**The only file here that changes often.** Update it when you finish a piece of
work. Everything else in `docs/` is stable by design.

Last updated: 2026-08-22

---

## Built and verified

**Schema** — `supabase/migrations/20260822000001_lane_all_initial_schema.sql`
covers all three lanes. Not yet applied to a live project (`supabase db push`).

**Lane 1 🔵 — backend, complete**
- `backend/intake/hard_checks.py` — deterministic gate, **16 tests passing**
- `backend/intake/parsing.py` — résumé PDF → `ParsedResume` via Gemini
- `backend/intake/screening.py` — the LLM screen, trusted/untrusted split enforced
- `backend/intake/invites.py` — token mint, hash-only storage, Resend email
- `backend/intake/repo.py` — Supabase access for lane 1's tables
- `backend/intake/pipeline.py` — parse → gate → screen → invite
- `backend/intake/question_builder.py` — the ADK workflow, **11 tests passing**
- `backend/api/routers/intake.py` — 9 endpoints, app boots, OpenAPI generates

**Lane 1 🔵 — frontend**
- `routes/intake/ApplicationForm.tsx` — public, with the consent gate
- `routes/intake/JobsPage.tsx` — create job, poll question-bank build
- `routes/intake/ReviewQueue.tsx` — human-in-the-loop decisions
- Typecheck clean, production build succeeds

**Shared**
- `shared/models/job.py` — `Job`, `ScreeningProfile`, `Question`, `RubricDimension`
- `shared/llm.py` — PDF input, dotted task keys, `Provenance` on every call
- Settings resolve lazily, so importing a module no longer needs a full `.env`
- `llm/prompts/` — `resume-parse`, `screen-application`, and all 7 `qb/` prompts

**27 tests passing.** `cd backend && ./.venv/bin/python -m pytest tests/ -q`

## Not yet done in lane 1

- **Nothing has run against real Gemini or a real Supabase project.** Every test
  so far is structural. The first live run is the real verification.
- Recruiter auth UI — the API checks JWTs, the frontend has no login page
- No rate limiting on the public application endpoint
- Calibration set (20–30 hand-scored answers) — required before real candidates,
  see D5

## Blocking other lanes

Nothing structurally. The migration and all shared models are in place, so:

- **🟡 Lane 2** can build against `InterviewPackage` and write `InterviewResult`.
  `POST /interview/redeem` is stubbed with its order of operations documented in
  `docs/contracts.md`.
- **🟢 Lane 3** can build against `InterviewResult`. Leaderboard and detail
  endpoints are stubbed.

## Known constraints to design around

- **ADK workflow agents are deprecated** (google-adk 2.7.1). `SequentialAgent`,
  `ParallelAgent`, `LoopAgent` still work but `Workflow` supersedes them. Known
  and accepted — see D22. Contained behind `build_workflow()`.
- **Gemini Live mid-session limits.** On `gemini-3.1-flash-live-preview`,
  `generate_reply()`, `update_instructions()` and `update_chat_ctx()` do not
  work mid-session and async function calling is unavailable. Adaptive probing
  must run through function calling plus a question state machine. The registry
  currently points at the 2.5 native-audio model, which has no such limits.
- **Speech-to-speech means no live diarization.** Multi-speaker detection runs
  post-call over recorded tracks.
- **`BackgroundTasks` is in-process.** A server restart mid-pipeline loses the
  work. Fine for the hackathon; the fix is a real queue and the interface does
  not change.
- **Resend needs a verified domain** before it will deliver to arbitrary
  addresses. Start DNS verification early.

## Open questions

- Should the interviewer greet candidates by name? Currently no — D14.
- Which Gemini Live model to settle on, given the mid-session limits.
- Who owns `interviewer-system.v1.md` — lane 2's prompt, built from lane 1's bank.

## Recently decided

D16–D22, all from the lane 1 build. Most consequential: **D16**, one question
bank per job rather than per candidate.
