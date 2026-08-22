# Architecture

Stable. If something here changes, it is a decision — log it in
`docs/decisions.md`.

## Tenancy

Everything below happens inside one organization. Nothing is global.

```
  organization ──< membership >── auth.users
       │
       ├──< job ──< application ──< interview ──< question_instance
       │             │      │                └──< integrity_event
       │             │      └──< interview_invite
       │             └──> candidate
       └──< candidate
```

Isolation is a database guarantee, not a coding convention (D25). Every
tenant-scoped table carries `org_id`, and children reference parents through
**composite** foreign keys:

```sql
job         UNIQUE (org_id, id)
application (org_id, job_id) -> job (org_id, id)
interview   (org_id, application_id) -> application (org_id, id)
```

A row whose `org_id` disagrees with its parent's cannot be inserted — Postgres
refuses it. That covers writes. **Reads still need filtering**, which the
database cannot enforce, so every function in `intake/repo.py` takes `org_id`.

The org is resolved from `membership` on every request (D27) — never from a JWT
claim, which goes stale when access changes, and never from a URL, which a
client could edit. The single unscoped lookup is `repo.get_job_unscoped()`, used
only by the public application form, where the candidate has no account and the
job id establishes the tenant.

`candidate` is scoped per organization (D26): a global row keyed on email would
let one company infer that someone had also applied to another.

## The pipeline

```
  Recruiter creates a job                                🔵 LANE 1
     │  screening_profile: given by hand, or extracted
     │    from the JD by Gemini (jd-to-requirements)
     │  ADK question_builder:
     │    JD → competencies → questions (parallel) → BARS rubrics
     │    → poison question → validate → loop until it passes
     ▼
  Application received                                   🔵 LANE 1
     │  resume PDF → Gemini native document input → ParsedResume
     │  hard checks (deterministic, no LLM)
     │    fail → rejected_screen: visible on the dashboard,
     │            reversible by inviting from that list
     │  screen-application → ScreeningDecision
     │    reject → rejected_screen   review → recruiter queue
     ▼
  Accepted → invite token minted, emailed as an expiring link
     │
     ▼
  Candidate clicks → POST /interview/redeem                🟡 LANE 2
     │  validate invite → create Interview + LiveKit room
     │  → dispatch agent with InterviewPackage as room metadata
     │  → return short-lived LiveKit access token
     ▼
  Voice interview (Gemini Live via LiveKit)
     │  question state machine walks InterviewPackage.questions
     │  adaptive follow-ups driven by the live signal
     │  browser proctor telemetry → POST /interview/events
     │  live correctness signal → Supabase realtime → recruiter view
     ▼
  Call ends
     │  post-call two-pass scoring → InterviewResult
     │  post-call diarization over recorded tracks → IntegrityReport
     ▼
  Leaderboard + candidate detail                          🟢 LANE 3
     │  ADK recruiter_chat: whole interview in context, tools for
     │  compare / draft / send
     ▼
  Outreach
```

## Stack

| Layer | Tech | Note |
|---|---|---|
| Frontend | React + Vite + TS, React Router, TanStack Query | team knows it — D6 |
| Backend | FastAPI + Pydantic v2 | all-Python so API and worker share models |
| Agents | Google ADK | before and after the call only — D9 |
| Voice | LiveKit Agents + Gemini Live API | LiveKit owns the in-call loop |
| Data | Supabase | Postgres + auth + storage + realtime — D7 |
| LLM | Gemini via `google-genai` | D4 |
| Email | Resend | |

## Why all-Python

Pydantic models in `backend/shared/models/` are one source of truth for three
consumers that would otherwise drift:

- **FastAPI** emits them as OpenAPI → `npm run gen:types` → frontend types
- **`google-genai`** takes them directly as `response_schema`
- **`api/` and `voice/`** import the same objects

That is why there is no separate `contracts/` folder and no hand-written JSON
Schema. Changing a model in `shared/models/` ripples everywhere at once — which
is the point, and also why it is a shared surface needing a heads-up.

## Processes

Two, from one dependency set in `backend/`:

```
uvicorn api.main:app --reload --port 8000    # HTTP
python -m voice.agent dev                    # LiveKit worker
```

The voice worker is **not** a web service. It subscribes to LiveKit job
dispatch, receives everything through room metadata, and writes results straight
to Supabase. Nothing makes requests to it — which is why there is no second
HTTP surface.

## Auth

Two audiences, two paths, deliberately not shared:

- **Recruiters** — Supabase Auth JWT verified in `api/deps.py`, then an
  organization resolved from `membership`. Both steps are required: the token
  says *who*, the membership says *what they may touch*.
- **Candidates** — no account. The invite token *is* the auth. Public routes
  only.

Never let a candidate-authenticated request reach a recruiter-scoped route.

Supabase signs session tokens with ES256 on new projects and HS256 on legacy
ones; both are verified (D23). `SUPABASE_JWT_SECRET` is optional and stays blank
on a new project.

## Where the LLM boundary sits

Every model call goes through `shared/llm.py::run(task, schema, ...)`, which
resolves prompt, model, and version from `llm/registry.json` and returns
`(parsed_output, Provenance)`. No handler builds a prompt inline.

ADK agents (`backend/agents/`) sit *outside* that helper — they orchestrate
multi-step work and manage their own model calls. Scoring never does; see D9.
