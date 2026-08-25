# Current state

**The only file here that changes often.** Update it when you finish a piece of
work. Everything else in `docs/` is stable by design.

If you are an agent reading this cold: check `docs/decisions.md` before
proposing anything. It records what was rejected and why.

Last updated: 2026-08-25

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
  `sitemap.xml` and `robots.txt` (D38)
- Public application form, consent recorded before the file is read
- Gemini parses the PDF natively, anchored to today's date (D30)
- Deterministic hard checks, deliberately permissive on ambiguity (D18)
- LLM screen with required evidence quotes and provenance
- Dashboard tiles, review queue, decisions recording `decided_by`
- Job pipeline cards now use a two-level hierarchy: Applications,
  Interviewing now, and Scored are prominent lime/lavender/ink summary cards;
  the remaining six states form a compact operational strip below them.
- Pipeline/Rubric folder tabs now use the same connected-edge geometry as the
  Jobs/Leaderboard navigation in both active states.
- `intake/question_builder.py` — ADK workflow (D9): SequentialAgent ->
  LlmAgent -> LoopAgent, 4 LLM sub-agents. Produces `job.rubric`: competencies,
  BARS anchors, weights. **Not questions** (D40)
- `intake/questions.py` — one `llm.run()` writing this candidate's probes from
  the rubric plus their resume. Dimensions are attached by rubric lookup, never
  copied by the model — that is what keeps two candidates comparable
- `intake/packaging.py` — `build_interview_package()`, the lane 2 handoff
- `intake/evidence.py` — ADK agent checking a candidate's claims against the
  GitHub link **they supplied** (D39). Verification, not sourcing: GitHub's AUP
  forbids using API data for recruiting outreach. Genuinely agentic — each
  finding decides the next call, unlike question_builder's fixed pipeline

## Lane 3 — merged

- `api/routers/insights.py` — org-scoped leaderboard and interview detail
- Recruiter frontend is implemented: `/leaderboard/:jobId` provides job-scoped
  ranking, search, review filtering, summary counts, percentile and all fixed
  rubric dimensions. It also charts composite-score distribution, applicable
  dimension averages, recommendation mix, and human-review mix from the same
  leaderboard response. KPI and analytics cards use the product's lime,
  lavender, ink, and offset-backed tile treatment. `/leaderboard/:jobId/candidates/:interviewId`
  provides the scored candidate detail with holistic strengths/concerns, review
  triggers, integrity evidence, per-question quotes/rationales, and
  model/prompt provenance. Null dimensions are shown as not applicable, never
  as zero.
- Candidate detail now includes the persisted recruiter score assistant.
  `GET/POST /insights/interviews/{interview_id}/chat` is recruiter- and
  org-scoped; an ADK `LlmAgent` receives the full interview dossier in user
  content and can inspect aggregate scores, question evidence, resume context,
  and review signals through deterministic tools. Assistant turns persist
  model/prompt provenance in `recruiter_chat_session.messages` (D5, D9, D11).
  The candidate page renders assistant replies as sanitized GitHub-flavored
  Markdown; recruiter messages remain literal text.
- The Insights reader normalizes score rows written before Lane 2 made
  `DimensionScore.band`, `transcript_summary`, and `human_review_reasons`
  required. This is read-only display compatibility: stored scores are never
  recalculated or rewritten. Verified against Acme: the two scored jobs return
  5 and 10 leaderboard entries respectively. Candidate detail also accepts the
  legacy `review_reasons` response name as a fallback for the current
  `human_review_reasons` contract.
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
The interview-completed hook now invokes the shared one-prompt scorer and
persists the normalized Lane 2 → Lane 3 handoff.

The worker now uses the custom ElevenLabs REST adapter with `eleven_flash_v2_5`
and raw 24 kHz mono PCM. The adapter initializes LiveKit's `AudioEmitter` as a
single non-streaming segment before pushing PCM, and a contract test covers the
emitter path. `livekit-plugins-deepgram` is explicitly declared in the `[voice]`
extra because the worker imports it at runtime.

The candidate room now requests camera and microphone through LiveKit, shows a
local camera preview, and provides mute, camera, and End call controls. Ending
the call or closing the tab disconnects the room; the worker awaits its
shutdown callback and marks an interview that fails the completion gate
`abandoned` instead of leaving it `in_progress`. Completion requires a non-empty
primary response for every configured question plus entry into the candidate
question period. Fullscreen and screen-share requests were removed from browser
proctoring. The interviewer closing prompt now offers a candidate question
period after the final configured question, then asks the candidate to click
End call.

The same room now renders LiveKit's native transcription stream in an
accessible, auto-scrolling **Live transcript** panel. Agent and candidate turns
are labelled `Verdikt` and `You`; interim text updates in place, and blank
partials are omitted. This avoids a second custom data-channel transcript path
and keeps the on-screen text aligned with the audio pipeline.

The worker records LiveKit's delivered assistant messages, including generated
greetings and interrupted speech, rather than the intended full script. It
checkpoints the accumulated transcript to `interview.transcript` after every
agent and candidate turn; a failed checkpoint is non-fatal because the next
full snapshot and shutdown persistence retry it. Incomplete calls retain this
transcript and any live signals but cannot run post-call scoring or publish an
`interview_score`. The persistence boundary independently rejects a result that
does not contain the complete configured question set.

Question delivery is gated on LiveKit's completed speech handle: an interrupted
or unfinished prompt is repeated and overlapping speech is not scored as its
answer. Scripted turns prefer LiveKit message IDs for transcript attribution,
with text matching only as a compatibility fallback. STT waits 1.5 seconds
before endpointing to reduce split answers.

Clarifications, explicit off-topic requests, prompt-injection attempts, and
short "I don't know" responses are deterministic branches. They do not advance
or become scored answers; injection attempts are checkpointed immediately as
integrity events. Follow-ups use one safe configured prompt and never read
internal guidance aloud. Live scoring may drive that follow-up but has a
two-second timeout so a provider delay cannot stall the call.

The completion screen polls the token-authenticated interview status and
distinguishes processing, completed, abandoned, and scoring-review states. End
call requests server-side room deletion before browser disconnect; tab close
sends the same request with `sendBeacon`. Terminal invites return 410 rather
than silently starting a second interview.

Current verification constraints and issues:

- A full Chrome media run on 2026-08-24 contained **10 questions**, not one.
  The worker received and asked `q1` through `q10` in package order, offered the
  candidate question period, delivered the closing, and ended through the UI.
- The Python state machine now owns question order. The introduction is not
  scored; each primary and follow-up answer is tagged to its question before
  the next prompt is spoken, and the final answer is committed before the
  candidate question period.
- Post-call scoring sends every recorded question through the canonical single
  `score-interview` call, applies the deterministic v2 aggregate, then writes
  `question_instance`, `question_scoring_claim`,
  `question_conversation_turn`, `question_rubric_assessment`, and finally
  `interview_score`. The recruiter-facing row is published last so Lane 3 does
  not observe a partially persisted result.
- Chrome verification used real LiveKit microphone and camera tracks with a
  deterministic audio capture. The final interview reached `completed` with 10
  question instances, 20 conversation turns, 34 scoring claims, 10 rubric
  assessments, and one published `interview_score` row.
- Post-call transcript timestamps are interview-relative milliseconds; Unix
  epoch milliseconds overflowed the database integer contract. The worker now
  allows 180 seconds for the shutdown callback so scoring and persistence are
  not killed by LiveKit's 10-second default.
- The frontend completed with no console errors. Its auth bootstrap emitted one
  non-blocking `Session lookup did not settle in time; continuing` warning.
- The live transcript was browser-verified at desktop and 320 px widths: the
  complete Verdikt greeting appeared incrementally, controls remained usable,
  and End call reached the ended screen with no console errors.
- End call now uses one native confirmation while questions remain; dismissing
  it keeps the call active, accepting it disconnects immediately. Tab close is
  never blocked. A real early-exit run persisted the generated greeting,
  finished as `abandoned`, and produced neither a result nor an
  `interview_score` row.
- A 2026-08-25 Chrome early-exit run confirmed camera/microphone controls, live
  candidate transcript rendering, confirmation dismissal, immediate room deletion
  (`ROOM_DELETED`), one persisted transcript turn, final `abandoned` status,
  interviewer provenance (`gemini-2.5-flash`, prompt v2), zero score rows, and
  zero matching LiveKit rooms.
- The ElevenLabs credential was rotated on 2026-08-25. Authentication and a
  real `eleven_flash_v2_5` PCM synthesis request both returned HTTP 200. The
  previous credential appeared in worker output before traceback redaction and
  must remain revoked; a fresh full spoken interview is still required after
  restarting the worker with the replacement key.
- HTTP/2 client loggers are clamped above DEBUG because protocol debug output
  can include authorization headers.

Redeem now delegates package construction to Lane 1's
`build_interview_package(application_id, org_id, interview_id)`. This preserves
D14's blind interviewer context and D27's tenant-scoped reads while supporting
D40's per-candidate question set.

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

**Decision numbers collided, twice.** Lane 3 added D31 and D32; lane 1 had
independently added its own D31 and D32, so lane 1 renumbered. Then lane 3's
second merge landed D31-D37 and collided again with the same lane 1 entries,
this time also rewriting one of their headings so `state.md` cited a D33 that
had become someone else's decision. Lane 1 renumbered again, to D38-D40, since
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
| Outreach drafting and sending | 3 |
| Remaining prompt stubs: `score-answer-live`, `score-holistic` | mixed |
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
  recorded rather than blocking the invite (D40)
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

D25-D40. Most consequential: **D25** (isolation enforced by the database),
**D30** (the model gets today's date), **D38** (Google for Jobs, not LinkedIn),
**D39** (verify claims from supplied links; never source strangers), **D40**
(fixed rubric per job, questions per candidate — supersedes D16).

D40 is the one to read before touching anything scoring-adjacent. The rule it
turns on: **the invariant a leaderboard needs is the scoring frame, not the
question wording.** Anchors must be portable — scorable without knowing which
probe produced the answer — so no anchor may name a technology. Verified on a
live build: 105 anchors, zero technology mentions.

D39 carries the four-verdict model, which is the part worth reading before
touching evidence: `supported` raises confidence, `related` raises it modestly,
`contradicted` lowers it, and `not_found` is **neutral**. A repository may only
contradict a claim if the candidate named that repository — otherwise it is a
different artifact, and a personal repo can never contradict private work.
