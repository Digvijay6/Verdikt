# Decision log

**Check this before proposing an approach.** Each entry records what was chosen,
why, and — most importantly — what was rejected. Rejected options are the point:
they are what stops the same debate happening every week.

Add an entry whenever you close off an alternative. Never delete one; if a
decision is reversed, add a new entry that supersedes it and say why.

---

## D1 · Voice-first from day one

**Chosen:** the screening interview is voice, not chat, from the first build.
**Rejected:** chat-first MVP with voice added later — the lower-effort path.
**Why:** voice is the product. A text interview is a different, weaker product
that would have to be thrown away.
**Cost accepted:** the voice pipeline is the heaviest part of the build.

## D2 · Browser-only proctoring, but aggressive

**Chosen:** no install. Every browser-reachable signal plus a server-side audio
pass, applied to *every* interview.
**Rejected:** browser extension (Tier 2) and downloadable client (Tier 3) for v1.
**Why:** install friction kills completion at the top of the funnel. A native
overlay sits outside the browser sandbox by construction, so no amount of
browser-side effort catches it — which means behavioural and content signals
matter more than pixel-hunting anyway, and those work without an install.
**Consequence:** detection is probabilistic, never a binary "tool X is running".
Surface likelihood plus evidence to a human. Revisit Tier 3 for senior or
regulated roles post-hackathon.

## D3 · Hybrid scoring

**Chosen:** a fast correctness-only signal during the call, then a full two-pass
re-score after it that overwrites the live value.
**Rejected:** post-call only (recruiter waits, worse demo); live only (too
shallow to rank on).
**Why:** the live signal also drives adaptive follow-ups, so it earns its cost
twice. Formula in `docs/rubric.md`.

## D4 · Gemini models

**Chosen:** Gemini across every task. Live API for the interview itself.
**Why:** hard requirement — this is a Gemini hackathon. Judges reward using
Gemini deeply rather than as a swappable text endpoint.
**Consequence:** see D5. Post-hackathon the model is changeable; the calibration
discipline is what makes that safe.

## D5 · Prompts and models are config, not code

**Chosen:** `llm/registry.json` maps each task to a prompt file, model, and
version. Every call returns a `Provenance` persisted with its output.
**Why:** scores are *not* portable across models or prompt versions. Same
prompt, different model, different distribution. A leaderboard ranking a March
score against a June score produced under a different model is silently lying.
**Required before real candidates:** a 20–30 answer calibration set, re-run on
every model or prompt change. See `docs/rubric.md`.

## D6 · FastAPI + React

**Chosen:** FastAPI backend, React + Vite frontend.
**Rejected:** Next.js with route handlers as the backend — genuinely fewer
moving parts, and the initial recommendation.
**Why:** nobody on the team has shipped Next.js. Learning App Router, server vs
client components, and its caching model under a hackathon deadline is a worse
trade than a slightly larger architecture the team already knows.
**Upside found:** going all-Python made Pydantic one source of truth for three
things — OpenAPI → frontend types, Gemini `response_schema`, and cross-lane
models. That is cleaner than the Next.js version, not merely equivalent.

## D7 · Supabase

**Chosen:** Supabase for Postgres, auth, storage, realtime.
**Clarification that caused confusion once:** Supabase *is* Postgres. Not an
alternative to it. Same engine, same scaling behaviour; what differs is who
operates it. Outgrowing it means `pg_dump` into RDS or Cloud SQL — the data was
never locked in. Only Auth/Storage/Realtime would need replacing.
**Constraint:** the browser never queries tables directly. Every write goes
through FastAPI, which holds the service key. RLS is defence in depth, not the
control. Candidate PII and interview audio make a single RLS mistake a breach.

## D8 · No Agno

**Rejected:** Agno as the agent framework.
**Why:** three reasons. LiveKit Agents *is* an agent loop, so Agno inside the
call means two loops fighting — and LiveKit closed the Agno-plugin request as
"not planned". Almost nothing in Verdikt is actually agentic; parsing, screening
and scoring are single structured calls. And it adds framework concepts to learn
on top of the domain concepts.

**Asked again later — Agno *alongside* ADK, in lane 1?** Also no.

- They solve the same problem. Two orchestration models and two failure modes
  for a lane containing exactly one multi-step workflow.
- Agno's multi-provider support is the usual argument for it, but Gemini is
  mandated (D4), and `llm/registry.json` already gives per-task model swapping
  (D5) — owned by us rather than rented from a framework.
- On a Google hackathon, a third-party framework sitting next to Google's own
  doing the same job reads as framework-collecting, not architecture.

Honest caveat: even ADK is a close call on engineering merit alone.
`question_builder` could be plain Python — a few `llm.run()` calls and a
`while not valid` loop. ADK wins on its Loop/Parallel primitives, its
step-through debugging UI, and being a judged Google product. That is one
framework's worth of justification, and it is fully spent. **Do not add a
second agent framework anywhere in this repo.**

## D9 · Google ADK before and after the call — never inside scoring

**Chosen:** ADK in exactly two places.
- **Before** — `question_builder`: JD → competencies → parallel question
  generation → BARS rubrics → poison question → validate → loop until it passes.
  Uses ADK's Sequential/Parallel/Loop workflow agents. 🔵 Lane 1.
- **After** — `recruiter_chat`: `LlmAgent` with tools and sessions. 🟢 Lane 3.

**Explicitly rejected:** ADK anywhere in the scoring path, even though scoring
happens "after the call".
**Why:** scoring must be reproducible, auditable, and defensible under GDPR
Art. 22 and NY AEDTA. An agent that picks its own trajectory varies run to run.
That is nondeterminism in the one component that legally cannot have it.
**Also rejected:** ADK inside the call — LiveKit owns that loop (same reason as
D8).

## D10 · No resume-parsing vendor

**Chosen:** Gemini reads resume PDFs natively as a document input, with a
Pydantic `response_schema`.
**Rejected:** Affinda, RChilli, or similar.
**Why:** one less vendor, one less contract, one less integration, and layout
and tables are handled natively.

## D11 · No RAG for the recruiter chat

**Chosen:** put the entire interview — transcript, per-question scores with
evidence, resume, integrity report — directly in the prompt.
**Rejected:** embeddings + pgvector + retrieval.
**Why:** a full interview is roughly 10–15k tokens against a 1M context window.
RAG here adds chunking bugs, a vector store, and *worse* citation accuracy, to
solve a problem that does not exist.

## D12 · Two tokens, different lifetimes

**Invite token** — days, single-redeem, in the emailed URL, stored as a hash.
**LiveKit access token** — minutes, scoped to one room and identity, minted
server-side at redeem, never emailed, never stored.
**Why it matters:** the invite redeems *once into an interview*, but revisiting
the URL while that interview is `IN_PROGRESS` and inside the rejoin window mints
a fresh access token for the same room. Strict single-use would kill any
candidate whose wifi drops mid-interview. Full order of operations in
`docs/contracts.md`.

## D13 · Poison questions as the primary anti-cheat

**Chosen:** one question per interview references technology that does not
exist. A model confabulates; a real candidate says they don't know it.
**Why:** highest signal per hour of work in the entire anti-cheat plan, and it
is a prompt rather than a model.
**Operational note:** rotate the fake names per job so they cannot be shared
between candidates.

## D14 · Blind interview conduct

**Chosen:** `InterviewPackage` omits the candidate's name and demographic
detail. The interviewer agent never sees them.
**Why:** the agent does not need them, and blind conduct is far easier to defend
than blind conduct retrofitted after a complaint.
**Open:** if the agent should greet candidates by name, that is a conscious
trade-off — raise it rather than quietly adding the field.

## D15 · Deferred, deliberately

Not forgotten, not in scope for the hackathon:

- Custom audio ML for TTS-bleed detection (pyannote / WavLM / AASIST). Needs
  labelled interview audio that does not exist yet. Diarization runs post-call
  on recorded tracks in the meantime.
- ATS integrations (Greenhouse, Lever, Workable). Manual job posting for now.
- Tier 2 extension and Tier 3 native proctoring client.
- Outcome loop — tying scores to 30/60/90-day performance.

---

## Provenance of the original plan

The pre-repo architecture research was produced by a different model driving web
search subagents. The *structure* held up; several *specifics* did not — stale
model names, at least two miscited arXiv IDs the subagent itself flagged, vendor
marketing claims relayed as fact, and two "competitors" that turned out not to
be recruiting products. Anything from that plan that is not re-verified in this
repo should be treated as unverified. Do not put its figures in a pitch.
