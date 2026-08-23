# Current state

**The only file here that changes often.** Update it when you finish a piece of
work. Everything else in `docs/` is stable by design.

If you are an agent reading this cold: check `docs/decisions.md` before
proposing anything. It records what was rejected and why.

Last updated: 2026-08-23

---

## Branches

`main` moves only through reviewed PRs. Nobody pushes to it directly.

| Lane | Branch | Merged to main |
|---|---|---|
| 1 — Intake | `intake` | yes, PR #1 |
| 3 — Insights | `dev/pranjal` | yes, PR #2 |
| 2 — Interview | `ai-call` | **not yet** |

```bash
git pull --rebase origin main    # take their work first
git push                          # your branch, never main
```

## Live environment

- Supabase project provisioned. **12 tables + 1 view**, every lane's
- Cross-org isolation **verified**: a cross-tenant insert is rejected by the
  composite foreign keys (D25)
- `resumes` bucket: private, PDF only, 10 MB
- **Gemini key live.** Model ids corrected against the API — two in the original
  registry did not exist. `gemini-3.7-flash` for extraction and speed,
  `gemini-3.1-pro-preview` where reasoning depth pays
- **Resend key live**, sandbox mode: delivers only to the account owner's
  address until a domain is verified
- **LiveKit credentials verified** (`ListRooms` 200)
- **All six migrations applied.** Teammates now have dashboard access and can
  run their own
- `docker compose up` boots api (:8000) and frontend (:5173) in ~3s

## Lane 1 — complete, verified end to end

Not "the code exists" — the whole path has been run against real Supabase,
Gemini and Resend, with a real resume, and the invite email arrived.

```
job created -> requirements extracted from the JD by Gemini
            -> ADK question_builder produces the *rubric*
   application received -> parsed -> hard checks -> LLM screen
            -> questions generated for this candidate from rubric + resume
            -> invite minted -> email delivered
```

- Signup, login, company onboarding. Passwords never reach our server
- `PUT /jobs/{id}` edit, `PUT /jobs/{id}/screening-profile`, `POST .../close`
- Public posting at `/j/{id}` with Google `JobPosting` JSON-LD, plus
  `sitemap.xml` and `robots.txt` (D33)
- Public application form, consent recorded before the file is read
- Gemini parses the PDF natively, anchored to today's date (D30)
- Deterministic hard checks, deliberately permissive on ambiguity (D18)
- LLM screen with required evidence quotes and provenance
- Dashboard tiles, review queue, decisions recording `decided_by`
- `intake/question_builder.py` — ADK workflow (D9): SequentialAgent ->
  LlmAgent -> LoopAgent, 4 LLM sub-agents. Produces `job.rubric`: competencies,
  BARS anchors, weights. **Not questions** (D35)
- `intake/questions.py` — one `llm.run()` writing this candidate's probes from
  the rubric plus their resume. Dimensions are attached by rubric lookup, never
  copied by the model — that is what keeps two candidates comparable
- `intake/packaging.py` — `build_interview_package()`, the lane 2 handoff
- `intake/evidence.py` — ADK agent checking a candidate's claims against the
  GitHub link **they supplied** (D34). Verification, not sourcing: GitHub's AUP
  forbids using API data for recruiting outreach. Genuinely agentic — each
  finding decides the next call, unlike question_builder's fixed pipeline

## Lane 3 — merged

- `api/routers/insights.py` — org-scoped leaderboard and interview detail
- `shared/interview_scoring.py` — deterministic seniority weights, ownership
  cap, consistency penalties, must-have cap, review triggers
- `interview_score` table plus rubric v2 aggregates (0-100 composite)
- `llm/prompts/score-answer.v2.md`, registry task bumped to v2
- `backend/scripts/seed_scoring_examples.py` prepares 40 normalized per-question
  Gemini inputs and relational rubric assessments for ten demo candidates
- `shared/post_call_scoring.py` sends one complete interview to
  `score-interview.v1`, validates question coverage/order, and attaches trusted
  context/provenance (D37)
- `scripts/score_job_interviews.py --job-id ...` scores completed, unscored
  interviews for one job and persists inputs, assessments, and aggregates
- Legacy `question_instance.scoring_input` and `fixed_rubric` JSONB are no
  longer read or written by the scoring seed
- `20260823110000_lane2_normalize_question_scoring_input.sql` is ready to push;
  it adds scalar question fields plus ordered claim and conversation tables
- `20260823111000_lane2_normalize_question_rubric_assessment.sql` is ready to
  push; it adds typed per-question measurements, evidence, and provenance (D35)

## Lane 2 — in flight on `ai-call`

Voice state machine, scoring pipeline, proctor, agent worker, redeem endpoint,
room metadata, silero VAD. Eight commits unmerged. They have added
`livekit-plugins-silero` and `structlog` to the `[voice]` extra.
Its interview-completed hook still needs to invoke the shared one-prompt scorer;
the job-id command is the executable integration path meanwhile.

**One change waiting for them.** Their redeem assembles the `InterviewPackage`
itself — fetching the application, validating `job.question_bank` into
`Question` objects, formatting a resume summary. All lane 1 models. Replace that
block (`api/routers/interview.py` on `ai-call`, ~lines 175-222) with
`build_interview_package(application_id, org_id, interview_id)`, about -32 lines
and +1. Until they do, jobs built after D35 hand them a null `question_bank` and
redeem fails loudly, which is the intended failure: better than silently parsing
a rubric into nonsense.

Two things that change on its own merits, not just for D35:

- Their inline summary opens with `resume_highlights.full_name`, which **D14
  forbids** — the interviewer agent is meant to be blind to name and
  demographics. `packaging.resume_summary()` omits it.
- Their redeem reads `application` joined to `job` with no `org_id` filter,
  relying on the invite lookup for scoping. `build_interview_package()` takes
  `org_id` and filters on it, per the repo rule.

## Three coordination failures worth learning from

All silent. All cost real time. Same shape each: two people pick the next
obvious number or edit the same shared file, and one side is overwritten
without anything erroring.

**Migration timestamp collision.** Two migrations shared `20260823090000`.
Supabase keys applied migrations by that prefix, so recording one marked the
version done and lane 3's `interview_score` **could never run** — while
`db push` reported success. Fixed by renaming lane 1's file and repairing the
remote history.
*Rule now in CLAUDE.md: generate timestamps with `date -u +%Y%m%d%H%M%S`.*

**`pyproject.toml` reverted by a merge.** `google-adk` disappeared and the
version pins went back to open ranges. Nothing failed, because the running
image had ADK from a cached Docker layer — a `--no-cache` rebuild or a fresh
clone would have died on `import google.adk`.
*Rule: `pyproject.toml` is a shared surface. And rebuild `--no-cache`
occasionally, because a cached layer hides a broken dependency list for days.*

**Decision numbers collided.** Lane 3 added D31 and D32; lane 1 independently
added its own D31 and D32. Renumbered lane 1's to D33 and D34, since lane 3's
were already merged.
*Rule now in CLAUDE.md: pull main before numbering anything, and if you collide,
renumber yours — the merged one stays put.*

## Not built

| Item | Lane |
|---|---|
| **JD file upload (PDF/DOCX)** — `jd_text` is paste-only | 1 |
| Rate limiting on the public application endpoint | 1 |
| Calibration set, 20-30 hand-scored answers (D5) | 1 |
| Consent screen copy per region, retention job | 1 |
| Concurrency and monthly limits recorded but unenforced | 1 / 2 |
| Browser proctor detectors — `frontend/src/lib/proctor/` empty | 2 |
| `recruiter_chat` ADK agent, outreach | 3 |
| Remaining prompt stubs: `interviewer-system`, `score-answer-live`, `score-holistic`, `recruiter-chat` | mixed |
| **Nothing is deployed** — Google for Jobs needs a public URL, Resend needs a verified domain | shared |

## Before writing a query

**Read D25-D27.** Every tenant-scoped table carries `org_id`, and composite
foreign keys reject a row whose org disagrees with its parent's. That stops bad
*writes* only — a missing filter on a *read* leaks just as much and the
database cannot catch it.

- `InterviewPackage` and `InterviewResult` both carry `org_id`
- Resolve the org from `current_recruiter`, never from a path parameter
- The one deliberate exception is `repo.get_job_unscoped()`, used only by the
  public application form, where the candidate has no account

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
  though the application is marked `failed` rather than sitting invisibly
- **Rubric builds take ~2 minutes** (4-6 LLM calls with a revise loop). Create
  jobs before a demo, not during one
- **Per-candidate question generation adds ~20s at invite**, one call. It runs
  in the background after the recruiter's request returns, and a failure is
  recorded rather than blocking the invite (D35)
- **Resend sandbox** delivers only to the account owner until a domain is
  verified

## Setup gotchas already hit

- **`npx supabase@latest`, not Homebrew** — Homebrew wants current Command Line
  Tools, which on macOS 26.x means a 7.4 GB OS update
- **Paste keys onto one line** — a wrapped key breaks `docker compose` with
  `invalid environment variable`, and the error does not say which line
- **`npx supabase migration list` before `db push`** — shows local versus
  remote, so a skipped migration is visible instead of silently succeeding
- **`backend/.venv` is Python 3.14, the container is 3.12.** The venv is a fast
  test loop; the container is the source of truth
- Supabase rejects `@example.com` addresses as invalid at signup

## Open questions

- Should the interviewer greet candidates by name? Currently no (D14)
- Which Gemini Live model to settle on, given the mid-session limits
- What does a candidate see when an org hits its concurrency limit? It must
  degrade to "try again shortly" with the invite still valid, never "your
  employer is on the free tier" — which means a queue, not a rejection
- Do we own a domain? Both Resend and Google for Jobs need one

## Recently decided

D25-D35. Most consequential: **D25** (isolation enforced by the database),
**D30** (the model gets today's date), **D33** (Google for Jobs, not LinkedIn),
**D34** (verify claims from supplied links; never source strangers), **D35**
(fixed rubric per job, questions per candidate — supersedes D16).

D35 is the one to read before touching anything scoring-adjacent. The rule it
turns on: **the invariant a leaderboard needs is the scoring frame, not the
question wording.** Anchors must be portable — scorable without knowing which
probe produced the answer — so no anchor may name a technology. Verified on a
live build: 105 anchors, zero technology mentions.

D34 carries the four-verdict model, which is the part worth reading before
touching evidence: `supported` raises confidence, `related` raises it modestly,
`contradicted` lowers it, and `not_found` is **neutral**. A repository may only
contradict a claim if the candidate named that repository — otherwise it is a
different artifact, and a personal repo can never contradict private work.
