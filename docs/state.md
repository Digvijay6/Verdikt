# Current state

**The only file here that changes often.** Update it when you finish a piece of
work. Everything else in `docs/` is stable by design.

Last updated: 2026-08-22

---

## The environment is live

Supabase project provisioned and the schema applied. This is no longer
theoretical — there is a real database behind the API.

- **9/9 tables present**, verified against the live project
- **`resumes` storage bucket** created: private, PDF only, 10 MB cap
- **Keys verified working** — publishable and secret both correct, and the
  secret key is not exposed to the browser
- **`docker compose up` boots both services in ~3s.** api on :8000 (healthy,
  OpenAPI serving), frontend on :5173 (HTTP 200)

**35 tests passing**, in the container on Python 3.12.

## Built

**Lane 1 🔵 — backend complete**
- `intake/hard_checks.py` — deterministic gate, 16 tests
- `intake/parsing.py` · `screening.py` · `invites.py` · `repo.py` · `pipeline.py`
- `intake/question_builder.py` — the ADK workflow, 11 tests
- `api/routers/intake.py` — 9 endpoints
- `api/deps.py` — JWT verification, both ES256/JWKS and legacy HS256, 8 tests

**Lane 1 🔵 — frontend**
- `ApplicationForm.tsx` (public, consent gate) · `JobsPage.tsx` ·
  `ReviewQueue.tsx`. Typecheck clean, production build succeeds.

**Shared**
- All Pydantic models; `shared/llm.py` with PDF input, dotted task keys, and
  `Provenance` on every call
- `llm/prompts/` — `resume-parse`, `screen-application`, 7 `qb/` prompts
- Docker Compose, versions pinned and checked against PyPI

## Blocked on one thing

**`GEMINI_API_KEY` is still a placeholder** (teammates are supplying it).
Everything that does not call Gemini works. Creating a job will start the
question-bank build and fail with `question_bank_status: failed` and the error
recorded on the job — that is correct behaviour, not a bug.

**The model ids in `llm/registry.json` are unverified.** They came from
documentation searches, not a live API. A wrong id fails at call time rather
than startup, so it will look fine until the first build silently fails. First
job once the key lands: list the models actually available and correct the
registry.

## Not built yet

| Item | Lane |
|---|---|
| Recruiter login UI — the API checks JWTs, the frontend has no login page | 🔵 |
| Rate limiting on the public application endpoint | 🔵 |
| Calibration set, 20–30 hand-scored answers (D5) | 🔵 |
| 6 of 8 prompts still stubs — `interviewer-system`, `score-*`, `recruiter-chat` | mixed |
| `backend/voice/**` — agent entrypoint stubbed only | 🟡 |
| Browser proctor detectors | 🟡 |
| `recruiter_chat` ADK agent, leaderboard, outreach | 🟢 |

## Blocking other lanes

Nothing. Schema, models, and contracts are all in place.

- **🟡 Lane 2** builds against `InterviewPackage`, writes `InterviewResult`.
  `POST /interview/redeem` is stubbed with its order of operations in
  `docs/contracts.md`.
- **🟢 Lane 3** builds against `InterviewResult`. Endpoints stubbed.

## Known constraints

- **ADK workflow agents are deprecated** in google-adk 2.7.1 — see D22.
  Contained behind `build_workflow()`.
- **Gemini Live mid-session limits** on `gemini-3.1-flash-live-preview`:
  `generate_reply()`, `update_instructions()`, `update_chat_ctx()` do not work
  mid-session and async function calling is unavailable. The registry points at
  the 2.5 native-audio model, which has no such limits.
- **Speech-to-speech means no live diarization.** Multi-speaker detection runs
  post-call over recorded tracks.
- **`BackgroundTasks` is in-process.** A restart mid-pipeline loses the work.
  Fine for now; the fix is a real queue and the interface does not change.
- **Resend needs a verified domain** before it delivers to arbitrary addresses.
- **Supabase free tier pauses after 7 days idle.** Hit the API during any quiet
  stretch before a demo, or it will be asleep when you need it.

## Setup gotchas already hit

- **Use `npx supabase@latest`, not Homebrew.** Homebrew wants current Command
  Line Tools, which on macOS 26.1 means a 7.4 GB OS update. `npx` downloads a
  prebuilt binary and sidesteps it entirely.
- **Paste keys onto one line.** A wrapped key breaks `docker compose` with
  `invalid environment variable`, and the message does not say which line.

## Open questions

- Should the interviewer greet candidates by name? Currently no — D14.
- Which Gemini Live model to settle on, given the mid-session limits.
- Who owns `interviewer-system.v1.md` — lane 2's prompt, built from lane 1's bank.

## Recently decided

D16–D24. Most consequential: **D16**, one question bank per job.
