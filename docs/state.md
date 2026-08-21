# Current state

**The only file here that changes often.** Update it when you finish a piece of
work. Everything else in `docs/` is stable by design.

Last updated: 2026-08-22

---

## Built

- Repo scaffold — full tree, pushed to `Digvijay6/Verdikt` on `main`
- `backend/shared/models/` — **all three model files are complete.** These are
  the cross-lane contracts. `candidate.py` 🔵, `interview.py` 🟡,
  `scoring.py` 🟡🟢
- `backend/shared/llm.py` — registry-driven `run(task, schema)`, returns
  `(parsed, Provenance)`
- `backend/shared/config.py`, `db.py`
- `backend/api/main.py` — app, CORS, routers mounted
- `backend/api/deps.py` — Supabase JWT verification
- `frontend/src/lib/api.ts` — typed client, public vs authenticated split
- `frontend/` — Vite + React + Router skeleton
- `llm/registry.json` — all 8 tasks registered
- `llm/prompts/score-answer.v1.md`, `screen-application.v1.md` — written
  properly, they encode the rubric and bias rules
- Docs: `architecture.md`, `decisions.md`, `contracts.md`, `rubric.md`,
  `compliance.md`, plus `CLAUDE.md`

## Blocking everyone

- **`supabase/migrations/` is empty.** No tables exist. Every lane is blocked on
  this. It is a shared surface, so it should be written once, not three times.
  Next up.

## Not built yet

| Item | Lane | Note |
|---|---|---|
| Migrations, all lanes | shared | **blocking — do first** |
| `backend/agents/question_builder/` | 🔵 | ADK Sequential → Parallel → Loop. Replaces the weakest prompt |
| Intake flow end to end | 🔵 | apply → parse → hard checks → screen → invite email |
| 6 of 8 prompts | mixed | `resume-parse`, `jd-to-rubric`, `interviewer-system`, `score-answer-live`, `score-holistic`, `recruiter-chat` are stubs |
| All router handlers | all | currently `raise NotImplementedError`, flow documented above each |
| `backend/voice/**` | 🟡 | agent entrypoint stubbed only |
| Browser proctor detectors | 🟡 | `frontend/src/lib/proctor/` empty |
| `backend/agents/recruiter_chat/` | 🟢 | ADK LlmAgent + tools + sessions |
| Frontend routes | all | placeholders |
| Calibration set | 🔵 | 20–30 hand-scored answers. Required before real candidates — see D5 |
| Consent screens | 🔵 | see `compliance.md` |

## Known constraints to design around

- **Gemini Live mid-session limits.** On `gemini-3.1-flash-live-preview`,
  LiveKit documents that `generate_reply()`, `update_instructions()`, and
  `update_chat_ctx()` do not work mid-session, and async function calling is
  unavailable. Adaptive probing must be driven by function calling plus a
  question state machine, not by rewriting instructions mid-call. The 2.5
  native-audio model does not have these limits — the registry currently points
  at 2.5. Record whichever is used in `Interview.model_id`.
- **Speech-to-speech means no live diarization.** Multi-speaker detection runs
  post-call over recorded tracks.

## Open questions

- Should the interviewer greet candidates by name? Currently no — see D14.
- Which Gemini Live model to settle on, given the mid-session limits above.
- Who owns `interviewer-system.v1.md` — it is lane 2's prompt but built from
  lane 1's question bank.

## Recently decided

See `docs/decisions.md`. Most recent: **D9** — ADK goes before and after the
call, never in the scoring path.
