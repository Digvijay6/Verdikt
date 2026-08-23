# Current state

**The only file here that changes often.** Update it when you finish a piece of
work. Everything else in `docs/` is stable by design.

Last updated: 2026-08-23

---

## Lane 1 is complete and verified end to end

Not "the code exists" — the whole path has been run against real Supabase,
real Gemini, real Resend, with a real resume, and the invite email arrived.

```
job created -> requirements extracted from the JD by Gemini
            -> ADK question_builder produces the bank
   application received -> parsed -> hard checks -> LLM screen
            -> invite minted -> email delivered
                                     |
                                     v
                          [ lane 2 takes over ]
```

**61 tests passing**, in the container on Python 3.12.

## Live environment

- Supabase project provisioned; **11 tables + 1 view**, all three lanes
- Cross-org isolation **verified**, not assumed: a cross-tenant insert is
  rejected by the composite foreign keys (D25)
- `resumes` bucket: private, PDF only, 10 MB
- **Gemini key live.** Model ids corrected against the API — two in the
  original registry did not exist
- **Resend key live**, sandbox mode: delivers only to the account owner's
  address until a domain is verified
- **LiveKit credentials verified** (`ListRooms` returns 200). Unused by lane 1;
  they belong to redeem, which is lane 2's
- `docker compose up` boots api (:8000) and frontend (:5173) in ~3s

## Built — lane 1

**Job setup**
- Create a job; Gemini extracts hard requirements from the JD, or supply them
- ADK `question_builder`: competencies, parallel question writers, BARS
  rubrics, poison question, validate-and-revise loop
- `PUT /jobs/{id}` — edit title, seniority, JD. Rebuilds the bank when the JD
  changes, because the questions came from it
- `PUT /jobs/{id}/screening-profile` — correct AI-extracted requirements,
  stamped with who reviewed them
- `POST /jobs/{id}/close` — stops applications, keeps the leaderboard
- Public posting at `/j/{id}` with Google `JobPosting` JSON-LD, plus
  `sitemap.xml` and `robots.txt` (D31)

**Application intake**
- Public form; consent recorded **before** the file is read
- Resume in a private bucket, served by short-lived signed URL
- Gemini parses the PDF natively, anchored to today's date (D30)
- Deterministic hard checks, deliberately permissive on ambiguity (D18)
- LLM screen with required evidence quotes and provenance
- Invite minted hash-only and emailed; an email failure does not erase the
  accept

**Recruiter surface**
- Dashboard tiles from one grouped query
- Review queue showing the model's evidence beside its recommendation
- Accept/reject recording `decided_by` — the compliance trail
- Screen-rejected candidates visible and reversible

**Foundation (shared)**
- Multi-tenancy enforced by the database (D25), per-org candidates (D26),
  org resolved from membership (D27)
- ES256 and legacy HS256 JWT verification (D23)
- Prompts and models as config, `Provenance` persisted on every call (D5)

## Bugs found by testing, not by tests

Each function was individually correct. Only running the real thing exposed
these:

- **Stale decisions surviving a re-application** — a re-uploaded resume kept
  the previous verdict, so one candidate displayed an accept citing evidence
  from a document they never submitted
- **The model guessing today's date** — "Present" resolved to its training
  cutoff, undercounting a current role by 1.4 years, silently (D30)
- **A failed email erasing an accept** — a Resend outage would have looked
  identical to never being accepted
- **A missing import turning a request body into a query parameter** — the
  endpoint returned 422 on arrival

## Not built

| Item | Lane |
|---|---|
| **JD file upload (PDF/DOCX)** — `jd_text` is paste-only | 1 |
| Org signup — `scripts/seed_dev.py` is the only way to create a company | 1 |
| Recruiter login UI — the API checks JWTs, the frontend has no login page | 1 |
| `build_interview_package()` — the last thing lane 1 owes lane 2 | 1 |
| Rate limiting on the public application endpoint | 1 |
| Calibration set, 20-30 hand-scored answers (D5) | 1 |
| Concurrency and monthly limits recorded but unenforced | 1 / 2 |
| 6 of 9 prompts still stubs — `interviewer-system`, `score-*`, `recruiter-chat` | mixed |
| `backend/voice/**` — entrypoint stubbed only | 2 |
| Browser proctor detectors | 2 |
| `recruiter_chat` ADK agent, leaderboard, outreach | 3 |

## For lanes 2 and 3

**Read D25-D27 before writing a query.** Every tenant-scoped table carries
`org_id` and composite foreign keys reject a mismatched row — but that stops
bad *writes* only. A missing filter on a *read* leaks just as much and the
database cannot catch it.

- `InterviewPackage` and `InterviewResult` both carry `org_id`
- Resolve the org from `current_recruiter`, never from a path parameter
- `POST /interview/redeem` is stubbed; order of operations in `docs/contracts.md`
- The concurrency check belongs in redeem
- **If `ai-call` was branched before the multi-tenancy rebuild, rebase onto
  `main` early** — every table gained `org_id` and both contracts changed shape

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
