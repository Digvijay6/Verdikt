# Verdikt

AI recruiter. Job posted → applications screened → AI voice interview → scored
leaderboard → recruiter chat that explains every score → outreach.

> **Start with [`CLAUDE.md`](CLAUDE.md)** — the shared context every person and
> AI agent on this repo reads first. `docs/state.md` is what's built right now;
> `docs/decisions.md` is what's already been settled and why. Check that one
> before proposing an approach.

## Stack

| Layer | Tech |
|---|---|
| Frontend | React + Vite + TypeScript, React Router, TanStack Query |
| Backend | FastAPI + Pydantic v2 |
| Voice | LiveKit Agents (Python) + Gemini Live API |
| Data | Supabase (Postgres, auth, storage, realtime) |
| LLM | Gemini via `google-genai` |
| Email | Resend |

## Lane ownership

Three people, one repo, disjoint folders.

| Lane | Owner | Owns |
|---|---|---|
| 1 — Intake | Aditya | `api/routers/intake.py` · `frontend/src/routes/intake` · `components/intake` · everything up to and including the invite email |
| 2 — Interview | | `backend/voice/**` · `api/routers/interview.py` · `frontend/src/routes/interview` · `lib/proctor` |
| 3 — Insights | | `api/routers/insights.py` · `frontend/src/routes/recruiter` · `components/insights` |

**Tables follow the same rule** — everyone reads, only the owner writes:

- Shared  `organization` `membership`
- Lane 1  `job` `candidate` `application` `interview_invite`
- Lane 2  `interview` `question_instance` `integrity_event`
- Lane 3  `recruiter_chat_session` `outreach_message`

### Tenancy — read this before writing a query

Multiple companies use this. Every tenant-scoped table carries `org_id`, and
children reference parents through composite foreign keys `(org_id, parent_id)`,
so a cross-org row **cannot be inserted** — Postgres refuses it.

That covers writes. Reads are on you: take `org_id` and filter on it. Resolve it
from `current_recruiter`, never from a path parameter and never from a token
claim. See D25–D27.

### Rules that keep this conflict-free

1. **Never edit another lane's folder.** Need something from it? Ask the owner.
2. **Five shared surfaces need a heads-up in chat before you touch them:**
   `backend/shared/` · `llm/` · `supabase/migrations/` ·
   `frontend/src/lib/api.ts` · `frontend/src/components/ui/`
3. **Migrations are additive only**, named `YYYYMMDDHHMMSS_lane_what.sql`.
   Never edit one that is already merged — write a new one.
4. **No `utils` catch-all file.** That is where merge conflicts breed. Keep
   helpers in your own lane even if two lanes end up with similar ones.

## The two handoffs

Everything else is internal to a lane. These two are contracts:

- **Lane 1 → 2** — `InterviewPackage` (`shared/models/interview.py`). Assembled
  at redeem time, passed into the LiveKit room as metadata.
- **Lane 2 → 3** — `InterviewResult` (`shared/models/scoring.py`). Note that
  `DimensionScore.evidence` is required — lane 3's chat cannot explain a score
  it has no quote for.

See `docs/contracts.md`.

## Running it

**First time? Read [SETUP.md](SETUP.md)** — accounts, keys, and the
Supabase bucket all need creating before any of this works.

```bash
docker compose up          # api :8000 · frontend :5173
```

Or without Docker:

```bash
# backend — API
cd backend && pip install -e ".[dev]"
uvicorn api.main:app --reload --port 8000     # docs at :8000/docs

# backend — voice worker (separate process, same deps)
python -m voice.agent dev

# frontend
cd frontend && npm install && npm run dev     # :5173

# regenerate frontend types after any Pydantic model change
npm run gen:types
```

## Prompts and models are config, not code

`llm/registry.json` maps each task to a prompt file, a model, and a version.
Swapping a model or bumping a prompt is an edit there, never a code change.
Every LLM call returns a `Provenance` — persist it with whatever the call
produced.

This matters more than it looks. Prompts and models both drift, and a
leaderboard that ranks a March score against a June score produced under a
different model is silently lying about who is better. Provenance plus a
calibration set is what makes model changes safe. See `docs/rubric.md`.

## Before candidates touch it

Consent copy, retention windows, and the human-review requirement are in
`docs/compliance.md`. GDPR Art. 22 and NY AEDTA both require a person in the
loop on rejections — the integrity score is evidence for a reviewer, never an
auto-reject.
