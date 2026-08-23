# Current state

**The only file here that changes often.** Update it when you finish a piece of
work. Everything else in `docs/` is stable by design.

Last updated: 2026-08-23

---

## The environment is live, and multi-tenant

Supabase project provisioned, schema rebuilt for multi-tenancy and applied.

- **11 tables + 1 view present**, verified against the live project. The new
  `interview_score` and scoring-rubric-v2 migrations are ready to push.
- **Cross-org isolation verified**, not assumed. Attaching an application to
  another org's job fails on `application_org_id_job_id_fkey`; pairing an org's
  job with another org's candidate fails on the candidate FK. Postgres refuses
  both — see D25
- **`resumes` bucket** created: private, PDF only, 10 MB cap
- **`docker compose up`** boots api (:8000) and frontend (:5173) in ~3s

**47 non-ADK backend tests passing.** The question-builder suite cannot collect
in the current local venv because `google.adk` is not installed.

## Built

**Tenancy (shared)**
- `shared/models/organization.py` — Organization, Membership, Plan, Role
- `shared/plans.py` — tier limits with per-org override
- `shared/tenancy.py` — membership resolution
- `api/deps.py` — org resolved from membership per request, 7 tests
- Repo scaffold — full tree, pushed to `Digvijay6/Verdikt` on `main`
- `backend/shared/models/` — **all three model files are complete.** These are
  the cross-lane contracts. `candidate.py` 🔵, `interview.py` 🟡,
  `scoring.py` 🟡🟢
- `backend/shared/llm.py` — registry-driven `run(task, schema)`, returns
  `(parsed, Provenance)`
- `backend/shared/config.py`, `db.py`
- `backend/api/main.py` — app, CORS, routers mounted
- `backend/api/deps.py` — Supabase JWT verification
- `backend/api/routers/insights.py` — org-scoped leaderboard and interview
  detail read `interview_score` rows and stored `InterviewResult` payloads
- `supabase/migrations/20260822000001_lane_all_initial_schema.sql` and
  `20260822120000_lane_all_multitenancy.sql` — shared tables for intake,
  interview, insights, and multi-tenant isolation
- `supabase/migrations/20260823090000_lane_all_interview_score.sql` — additive
  `interview_score` table for leaderboard/detail score reads
- `supabase/migrations/20260823100000_lane_all_scoring_rubric_v2.sql` — additive
  0-100 rubric aggregates and review reasons for `interview_score`
- `backend/shared/interview_scoring.py` — deterministic seniority weights,
  ownership cap, consistency penalties, must-have cap, and review triggers
- `llm/prompts/score-answer.v2.md` — fixed technical accuracy, depth, ownership,
  follow-up resilience, and consistency anchors; registry task bumped to v2
- `frontend/src/lib/api.ts` — typed client, public vs authenticated split
- `frontend/` — Vite + React + Router skeleton
- `llm/registry.json` — all 8 tasks registered
- `llm/prompts/score-answer.v2.md`, `screen-application.v1.md` — written
  properly, they encode the rubric and bias rules
- Docs: `architecture.md`, `decisions.md`, `contracts.md`, `rubric.md`,
  `compliance.md`, plus `CLAUDE.md`

**Lane 1 — backend**
- `intake/hard_checks.py` — deterministic gate, 16 tests
- `intake/requirements.py` — Gemini extracts hard requirements from the JD
- `intake/parsing.py` · `screening.py` · `invites.py` · `repo.py` · `pipeline.py`
- `intake/question_builder.py` — the ADK workflow, 11 tests
- `api/routers/intake.py` — 11 endpoints, all org-scoped

**Lane 1 — frontend**
- `ApplicationForm.tsx` (public, consent gate) · `JobsPage.tsx` (with pipeline
  tiles) · `ReviewQueue.tsx`. Typecheck clean, production build succeeds.

**Shared**
- `shared/llm.py` — PDF input, dotted task keys, `Provenance` on every call
- `llm/prompts/` — `resume-parse`, `screen-application`, `jd-to-requirements`,
  7 `qb/` prompts
- Docker Compose, versions pinned and checked against PyPI

## Blocked on one thing

**`GEMINI_API_KEY` is still a placeholder.** Everything that does not call
Gemini works. Creating a job starts requirement extraction and the question-bank
build; both will fail and record their errors on the job — correct behaviour,
not a bug.

**The model ids in `llm/registry.json` are unverified.** They came from
documentation, not a live API. A wrong id fails at call time rather than
startup, so it looks fine until the first build silently fails.

## Not built yet

| Item | Lane |
|---|---|
| **JD file upload (PDF/DOCX)** — `jd_text` is paste-only | 1 |
| Org signup — `scripts/seed_dev.py` is the only way to create a company | 1 |
| Recruiter login UI — the API checks JWTs, the frontend has no login page | 1 |
| `build_interview_package()` — the last thing lane 1 owes lane 2 | 1 |
| Rate limiting on the public application endpoint | 1 |
| Calibration set, 20–30 hand-scored answers (D5) | 1 |
| Remaining prompt stubs — `interviewer-system`, `score-answer-live`, `score-holistic`, `recruiter-chat` | mixed |
| `backend/voice/**` — agent entrypoint stubbed only | 2 |
| Browser proctor detectors | 2 |
| `recruiter_chat` ADK agent and outreach | 3 |
- Initial migrations now exist. They still need to be pushed to Supabase before
  backend routes can return real data.

## Not built yet

| Item | Lane | Note |
|---|---|---|
| Push migrations to Supabase | shared | run `supabase db push` after linking the project |
| `backend/agents/question_builder/` | 🔵 | ADK Sequential → Parallel → Loop. Replaces the weakest prompt |
| Intake flow end to end | 🔵 | apply → parse → hard checks → screen → invite email |
| Remaining prompt stubs | mixed | `interviewer-system`, `score-answer-live`, `score-holistic`, and `recruiter-chat` |
| Most router handlers | mixed | intake/interview remain stubbed; insights leaderboard/detail reads are wired |
| `backend/voice/**` | 🟡 | agent entrypoint stubbed only |
| Browser proctor detectors | 🟡 | `frontend/src/lib/proctor/` empty |
| `backend/agents/recruiter_chat/` | 🟢 | ADK LlmAgent + tools + sessions |
| Frontend routes | all | placeholders |
| Calibration set | 🔵 | 20–30 hand-scored answers. Required before real candidates — see D5 |
| Consent screens | 🔵 | see `compliance.md` |

## For lanes 2 and 3

**Read D25-D27 before writing a query.** Every tenant-scoped table carries
`org_id` and composite foreign keys reject a mismatched row — but that stops
bad *writes* only. A missing filter on a *read* leaks just as much and the
database cannot catch it.

- Every tenant-scoped table carries `org_id`, and composite foreign keys reject
  a row whose org disagrees with its parent's.
- `InterviewPackage` and `InterviewResult` both carry `org_id` now.
- Resolve the org from `current_recruiter`, never from a path parameter.
- **Lane 2** — `POST /interview/redeem` is stubbed; order of operations in
  `docs/contracts.md`. The concurrency check belongs here.
- **Lane 3** — leaderboard and detail endpoints read `interview_score`; the
  recruiter chat agent and outreach actions are still pending.

## Known constraints

- **ADK workflow agents are deprecated** in google-adk 2.7.1 (D22), contained
  behind `build_workflow()`
- **Gemini Live mid-session limits** on `gemini-3.1-flash-live-preview`:
  `generate_reply()`, `update_instructions()`, `update_chat_ctx()` do not work
  mid-session, and async function calling is unavailable. The registry points
  at the 2.5 native-audio model, which has no such limits
- **Speech-to-speech means no live diarization** — multi-speaker detection runs
  post-call over recorded tracks
- **`BackgroundTasks` is in-process** — a restart mid-pipeline loses the work,
  though the application is now marked `failed` rather than sitting invisibly
- **Question bank builds take ~4 minutes** (11 LLM calls with a revise loop).
  Create jobs before a demo, not during one
- **Nothing is deployed.** Google for Jobs needs a public URL, and Resend needs
  a verified domain before it will mail anyone but the account owner

## Setup gotchas already hit

- **`npx supabase@latest`, not Homebrew** — Homebrew wants current Command Line
  Tools, which on macOS 26.x means a 7.4 GB OS update
- **Paste keys onto one line** — a wrapped key breaks `docker compose` with
  `invalid environment variable`, and the error does not say which line
- **`db push --include-all`** when a migration is not the latest by timestamp
- **`backend/.venv` is Python 3.14, the container is 3.12.** The venv is a fast
  test loop; the container is the source of truth. Verify there before trusting

## Open questions

- Should the interviewer greet candidates by name? Currently no (D14)
- Which Gemini Live model to settle on, given the mid-session limits
- Who owns `interviewer-system.v1.md` — lane 2's prompt, built from lane 1's bank
- What does a candidate see when an org hits its concurrency limit? It must
  degrade to "try again shortly" with the invite still valid, never "your
  employer is on the free tier" — which means a queue, not a rejection
- Do we own `verdikt.app`? Both Resend and Google for Jobs need a real domain

## Recently decided

D25-D31. Most consequential: **D25** (isolation enforced by the database),
**D30** (the model gets today's date), **D31** (Google for Jobs, not LinkedIn).
