# Current state

**The only file here that changes often.** Update it when you finish a piece of
work. Everything else in `docs/` is stable by design.

Last updated: 2026-08-22

---

## The environment is live, and multi-tenant

Supabase project provisioned, schema rebuilt for multi-tenancy and applied.

- **11 tables + 1 view present**, verified against the live project
- **Cross-org isolation verified**, not assumed. Attaching an application to
  another org's job fails on `application_org_id_job_id_fkey`; pairing an org's
  job with another org's candidate fails on the candidate FK. Postgres refuses
  both — see D25
- **`resumes` bucket** created: private, PDF only, 10 MB cap
- **`docker compose up`** boots api (:8000) and frontend (:5173) in ~3s

**42 tests passing.**

## Built

**Tenancy (shared)**
- `shared/models/organization.py` — Organization, Membership, Plan, Role
- `shared/plans.py` — tier limits with per-org override
- `shared/tenancy.py` — membership resolution
- `api/deps.py` — org resolved from membership per request, 7 tests

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
| Org creation + first-membership flow — no way to sign up a company yet | 1 |
| Recruiter login UI — the API checks JWTs, the frontend has no login page | 1 |
| Concurrency and monthly limits are recorded but nothing enforces them | 1 / 2 |
| Rate limiting on the public application endpoint | 1 |
| Calibration set, 20–30 hand-scored answers (D5) | 1 |
| 6 of 9 prompts still stubs — `interviewer-system`, `score-*`, `recruiter-chat` | mixed |
| `backend/voice/**` — agent entrypoint stubbed only | 2 |
| Browser proctor detectors | 2 |
| `recruiter_chat` ADK agent, leaderboard, outreach | 3 |

## Blocking other lanes

Nothing, but **both lanes must read D25–D27 before writing queries.**

- Every tenant-scoped table carries `org_id`, and composite foreign keys reject
  a row whose org disagrees with its parent's.
- `InterviewPackage` and `InterviewResult` both carry `org_id` now.
- Resolve the org from `current_recruiter`, never from a path parameter.
- **Lane 2** — `POST /interview/redeem` is stubbed; order of operations in
  `docs/contracts.md`. The concurrency check belongs here.
- **Lane 3** — leaderboard and detail endpoints stubbed.

## Known constraints

- **ADK workflow agents are deprecated** in google-adk 2.7.1 — D22. Contained
  behind `build_workflow()`.
- **Gemini Live mid-session limits** on `gemini-3.1-flash-live-preview`:
  `generate_reply()`, `update_instructions()`, `update_chat_ctx()` do not work
  mid-session and async function calling is unavailable. The registry points at
  the 2.5 native-audio model, which has no such limits.
- **Speech-to-speech means no live diarization.** Multi-speaker detection runs
  post-call over recorded tracks.
- **`BackgroundTasks` is in-process.** A restart mid-pipeline loses the work,
  though the application is now marked `failed` rather than sitting invisibly at
  `received`.
- **Resend needs a verified domain** before it delivers to arbitrary addresses.
- **Supabase free tier pauses after 7 days idle.** Hit the API during any quiet
  stretch before a demo.

## Setup gotchas already hit

- **Use `npx supabase@latest`, not Homebrew.** Homebrew wants current Command
  Line Tools, which on macOS 26.x means a 7.4 GB OS update.
- **Paste keys onto one line.** A wrapped key breaks `docker compose` with
  `invalid environment variable`, and the message does not say which line.
- **`db push --include-all`** is needed when a migration is not the latest by
  timestamp.

## Open questions

- Should the interviewer greet candidates by name? Currently no — D14.
- Which Gemini Live model to settle on, given the mid-session limits.
- Who owns `interviewer-system.v1.md` — lane 2's prompt, built from lane 1's bank.
- What does a candidate see when an org hits its concurrency limit? It has to
  degrade to "try again shortly" with the invite still valid — never "your
  employer is on the free tier". That means a queue, not a rejection.

## Recently decided

D25–D29, all from the multi-tenancy rebuild. Most consequential: **D25**,
isolation enforced by composite foreign keys rather than by remembering to
filter.
