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
  Uses ADK's Sequential/Parallel/Loop workflow agents. Lane 1.
- **After** — `recruiter_chat`: `LlmAgent` with tools and sessions. Lane 3.

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

## D16 · Question bank is generated once per job — SUPERSEDED by D40

**Superseded 2026-08-23.** The reasoning below is sound about *what* has to stay
constant and wrong about *which part of the interview that is*. Kept because the
comparability argument still applies — D35 satisfies it differently.

**Chosen:** one bank per job. Every candidate for a role gets the identical
questions and the identical rubric.
**Rejected:** tailoring questions to each candidate's resume.
**Why:** tailoring destroys score comparability. If candidate A got easier
questions, ranking them against B on the same leaderboard is meaningless. It
also reintroduces exactly the bias structured interviewing exists to remove —
same questions, same rubric, same conditions is the whole basis for defending
the process. Cheaper too: one workflow run per job rather than per applicant.
**Still adaptive:** follow-ups within an interview vary by answer (lane 2). The
*scored* questions stay constant.

## D17 · Applications arrive via a public per-job form

**Chosen:** `POST /intake/applications`, no account, résumé PDF upload.
**Why:** ATS integration is deferred (D15) and CSV import is demo-only. A real
form is also where the consent checkbox lives, which has to exist before any
résumé is processed.

## D18 · Hard checks are deterministic and run before the LLM

**Chosen:** plain Python over `ScreeningProfile` — years, required skills,
location. No model. Only survivors reach the LLM screen.
**Why:** free, instant, and testable. A rule you can read and point at in a
dispute is the only defensible way to reject someone automatically.
**Design bias, deliberate:** every ambiguous case passes through rather than
rejecting. Unknown years of experience passes. Unknown location passes. Work
authorization is never auto-failed — it is not inferable from a résumé and
guessing at it is both unreliable and legally hazardous. **A false reject is
invisible and unappealable**, so the gate leans toward letting the LLM screen
(which sees everything and can say `review`) make the call.

## D19 · `review` outcomes go to a recruiter queue

**Chosen:** `accept` auto-sends the invite; `reject` writes the decision and
sends nothing; `review` waits in a queue where a human accepts or rejects.
**Why:** this is where compliance.md's human-in-the-loop requirement physically
lives. The queue shows the model's evidence quotes beside its recommendation —
a recommendation without its evidence invites rubber-stamping, which is the
failure mode the review step exists to prevent.

## D20 · Candidate identity is keyed on email

**Chosen:** one `candidate` row per email (Postgres `citext`, so casing is
handled by the database rather than by every caller remembering to normalise).
`application` is the per-job row, unique on `(job_id, candidate_id)`.
**Why:** without it, one person applying twice becomes two leaderboard entries.

## D21 · ADK sub-agent prompts live in llm/prompts like everything else

**Chosen:** `registry.json` gains nested blocks addressed with dotted keys —
`llm.run("question-builder.validator", ...)`. Flat `jd-to-rubric` removed; the
workflow replaces it.
**Why:** keeps D5 honest. One place to look when a model needs changing.
**Implementation note:** ADK substitutes `{key}` in string instructions from
session state, which mangles any prompt containing a JSON example — and most of
these do. Instructions are therefore built by a callable
(`_instruction()` in `question_builder.py`) rather than passed as strings.

## D22 · Building on ADK's deprecated workflow agents, knowingly

**Chosen:** `SequentialAgent` / `ParallelAgent` / `LoopAgent`.
**The catch:** as of google-adk 2.7.1 all three are **deprecated** in favour of
`google.adk.workflow.Workflow`, an edge-based graph API. Every tutorial, blog
post, and doc page still uses the deprecated classes — this was only found by
installing the package and reading the warnings.
**Why proceed anyway:** they work now; removal is "a future version"; `Workflow`
cannot yet be used as an `LlmAgent` sub-agent, so it is still settling; and the
learning material a newcomer will reach for all uses the old API.
**Why it is safe to defer:** the entire dependency is behind `build_workflow()`
in one file. Migration is contained.
**Revisit:** before launch, not before the hackathon. The deprecation warning is
filtered in `backend/pytest.ini` with a pointer here — delete that filter when
migrating.

---

## D23 · Verify Supabase JWTs both ways, asymmetric first

**Chosen:** `api/deps.py` verifies ES256/RS256 against the project's JWKS
endpoint, and falls back to HS256 only when a shared secret is configured.
`SUPABASE_JWT_SECRET` is optional and left blank on new projects.

**Why this exists at all:** Supabase renamed its API keys — *publishable*
(`sb_publishable_…`) replaces `anon`, *secret* (`sb_secret_…`) replaces
`service_role` — and new projects sign session tokens with **ES256**, not the
legacy HS256 shared secret. The original `deps.py` only did HS256, so recruiter
auth would have failed on **every** request on a freshly created project. Not
degraded — completely broken, and only discoverable at the moment someone first
tries to log in.

**On algorithm confusion:** the algorithm is read from the token header, which
is normally where these attacks start. It is safe here because each branch is
pinned to a disjoint algorithm list and a distinct key, and the HS256 branch is
unreachable unless a shared secret is actually configured — an HS256 token
arriving at a project with no secret did not come from that project.

**Covered by 8 tests** against real signatures rather than mocked verification:
wrong signing key, expired, wrong audience, `alg: none`, and HS256 with no
secret configured.

**The general lesson, worth keeping:** the *library* versions were right because
pip resolves them. The *dashboard naming* was wrong because it only lived in
memory. Anything verifiable by running should be verified by running.

## D24 · Docker for parity, not for services

**Chosen:** compose runs the API, the frontend, and (behind a profile) the voice
worker. Nothing stateful runs locally — Supabase, Gemini and LiveKit are all
hosted.

**Why bother then:** the value is not isolation, it is that three people on
three machines run identical Python and Node. Version drift across a team
produces bugs that reproduce for exactly one person, which are the most
expensive kind to chase.

**Python pinned to 3.12**, and all dependencies pinned with `~=` rather than
open `>=` ranges, checked against current PyPI releases.

**The Supabase CLI is deliberately *not* in the image.** It is a host-side dev
tool that talks to the hosted project over the network — not part of the running
app. Use `npx supabase@latest`; Homebrew requires current Command Line Tools,
which on macOS 26.1 means a 7.4 GB OS update for no benefit.

**Lane 2's LiveKit stack is a `[voice]` extra**, so lanes 1 and 3 never install
an audio toolchain they do not import. One image serves both processes via an
`EXTRAS` build arg.

---

## D25 · Tenancy enforced by the database, not by discipline

**Chosen:** every tenant-scoped table carries `org_id`, and every child
references its parent through a **composite** foreign key `(org_id, parent_id)`.

```sql
job         UNIQUE (org_id, id)
application (org_id, job_id) -> job (org_id, id)
interview   (org_id, application_id) -> application (org_id, id)
```

**Rejected:** plain `org_id` columns filtered in application code.
**Why:** the plain version works until someone forgets a `WHERE` clause once,
and the failure mode is showing one company their competitor's candidates.
With composite keys, a row whose `org_id` disagrees with its parent's **cannot
be inserted** — Postgres refuses it. Forgetting a filter becomes a visible bug
rather than a silent cross-tenant leak.

**Verified**, not assumed: attaching an application to another org's job fails
on `application_org_id_job_id_fkey`, and pairing an org's job with another org's
candidate fails on `application_org_id_candidate_id_fkey`.

**Reads still need filtering.** The database stops bad *writes*; a missing
filter on a *read* leaks just as much and Postgres cannot catch it. Every
function in `intake/repo.py` therefore takes `org_id` and filters on it.

**One deliberate exception:** `repo.get_job_unscoped()`, used by the public
application form only. A candidate has no account, so the job id in their URL is
what establishes the tenant. Everything downstream then uses `job.org_id` rather
than anything the client sent. Nothing behind authentication may call it.

## D26 · Candidates are per-organization (amends D20)

**Chosen:** `candidate` is unique on `(org_id, email)`, not on `email`.
**Why:** a global candidate row means the same person applying to two of your
customers shares one record — and company A can then infer that they also
applied to company B. That is a privacy leak, not a modelling preference.
**Cost accepted:** no cross-org deduplication, which is a feature nobody wants.

## D27 · Organization comes from membership, never from the URL or the token

**Chosen:** `current_recruiter` resolves the org from the `membership` table on
every request. Users with one membership need nothing; users with several send
`X-Org-Id`.

**Why not the JWT:** a token claim goes stale the moment access changes.
Revoking someone should take effect immediately, not when their session next
refreshes.

**Why not a path parameter:** if the URL carried the tenant, a client could ask
for another tenant's data by editing it. The URL never carries the tenant.

**Why membership rather than `user.org_id`:** agencies and consultants work
across companies. Ten lines of SQL now; rewriting every query later.

**Why 403 and not 404** for an org the user does not belong to: distinguishing
"no such organization" from "not yours" lets anyone probe for which org ids
exist.

## D28 · AI-extracted hard requirements, ungated but visible

**Chosen:** omit `screening_profile` when creating a job and Gemini extracts the
hard requirements from the JD. Provenance is recorded. **No approval gate.**

**Rejected:** blocking a job from accepting applications until a human approves
the extracted requirements.
**Why rejected:** the meaningful human decision is at the leaderboard — which
candidates to bring in for a real interview. Gating the pipeline before that
adds friction to the thing the product exists to automate.

**The risk this leaves, and how it is handled:** candidates rejected by the hard
checks never reach a leaderboard, so leaderboard review cannot cover them. If
the model misreads "5+ years preferred" as a hard minimum, most applicants
vanish silently. So instead of a gate:

- Screen-rejected candidates land in `rejected_screen` and stay visible on the
  dashboard as a counted tile, not deleted
- Inviting one from that list overrides the filter — the rejection is reversible
- The extraction prompt is written to be extremely conservative: when torn
  between required and preferred, it must choose preferred, because a weak
  candidate reaching the screen costs one cheap model call while a strong one
  wrongly filtered is gone and nobody finds out

**Net:** stronger than a rubber-stamped approval checkbox would have been, and
without the friction.

## D29 · Closed jobs keep everything

**Chosen:** `job.status` of `draft | open | closed | archived`. Closing stops
new applications and changes nothing else — the leaderboard, transcripts,
scores and question bank all remain.
**Why:** a filled role is still an asset to the company (who did we interview,
reopen a similar role and reuse the bank), and `compliance.md` requires decision
records for 24 months regardless.
**Consequence to handle later:** this collides with a candidate's right to
erasure. The resolution is the standard one — delete personal data, keep the
anonymised decision record. Per-org candidates (D26) already make that
separable.

---

## D30 · Every prompt that reasons about time gets today's date

**Chosen:** the current date is injected into `resume-parse` and
`screen-application`, and both take an optional `today` so tests can pin it.

**Why:** a language model does not know what day it is. Asked to interpret
"Present" on a resume, it places the present somewhere near its training
cutoff — silently, and with a plausible-looking number.

**Measured, not theorised.** The same resume, running from June 2018 with a
current role from March 2021:

| | total_years_experience |
|---|---|
| Without a date anchor | 6.8 |
| With `today = 2026-08-22` | 8.2 |
| Actual | 8.1 |

Off by 1.4 years, in the direction that undercounts. On a job with a five-year
minimum that is the difference between an interview and a rejection the
candidate is never given a reason for.

**The general rule:** anything a model cannot know from its inputs must be
supplied explicitly. The date is the obvious one; it will not be the last.

**Prompt bumped to `resume-parse.v2.md`** rather than edited in place, per D5 —
years computed under v1 are not comparable to v2, and the version stamped on
each application is what makes that visible.

---

## D31 · Scores get a table, explanations stay in the contract JSON

**Chosen:** post-call scoring writes one `interview_score` row per interview.
The table carries rankable summary columns (`overall`, `display_score`,
`recommendation`, `integrity`, provenance) and the full
`InterviewResult` JSON.

**Rejected:** keeping scores only as columns on `interview`, and rejected
fully normalising every dimension/evidence quote into SQL tables.

**Why:** the leaderboard needs cheap, indexed reads over scores by
`(org_id, job_id)`, while the recruiter detail/chat needs the exact structured
contract with evidence quotes. Fully normalising the entire score tree would
make every contract change a migration and would split the legally important
explanation across many rows. Storing the full contract beside indexed summary
columns gives Lane 3 fast ranking without losing auditability.

**Tenant rule:** `interview_score` carries `org_id` and uses composite foreign
keys back to `interview`, `application`, and `job`, matching D25.

---

## D32 · Fixed 0-100 rubric, deterministic aggregation

**Chosen:** `score-answer.v2` extracts five fixed measurements: technical
accuracy, project depth, ownership, follow-up resilience, and consistency.
Plain Python applies the ownership cap, consistency penalties, seniority
weights, must-have cap, and human-review triggers. The leaderboard ranks on the
resulting 0-100 `composite_score`.

**Rejected:** asking Gemini for the final composite or review decision, and
keeping the earlier 55% per-question / 30% holistic / 15% role-fit formula as a
second ranking score.

**Why:** fixed anchors make candidates comparable; deterministic arithmetic
makes the outcome reproducible and auditable. Two simultaneous composite
formulas would let the detail page and leaderboard disagree. Holistic and role
fit remain available as explanatory v1 compatibility data but do not alter a
v2 composite.

**Compatibility:** `overall` remains as `1 + 4 * composite / 100`, allowing old
1-5 consumers and v1 rows to remain readable. New rows carry both values and
their rubric/model/prompt provenance.

**Integrity:** integrity evidence triggers human review but does not reduce the
v2 composite and never causes automatic rejection. This supersedes the earlier
unimplemented note about a multiplicative integrity penalty.

## D33 · Snapshot each question's scoring request and response

**Chosen:** `question_instance` stores the exact structured `scoring_input`
sent to Gemini and the validated `fixed_rubric` response as JSONB.

**Rejected:** reconstructing model input later from the current job bank,
transcript, and parsed resume.

**Why:** those source records can be corrected or versioned after an interview.
Reconstruction would then produce a plausible payload that is not necessarily
what the model actually saw. Immutable request/response snapshots make a score
reproducible and reviewable without fully normalising the explanation tree.

## D34 · Normalize Gemini scoring input

**Chosen:** scalar question context lives on `question_instance`; ordered resume
and prior-answer claims live in `question_scoring_claim`; ordered transcript
turns live in `question_conversation_turn`. Gemini user content is assembled
from those rows at call time. The `fixed_rubric` response remains JSONB.

**Rejected:** continuing to write the whole scoring request into
`question_instance.scoring_input` JSONB, and putting repeated claims or
conversation turns into arrays on the parent row.

**Why:** the request structure is stable operational data that needs ordinary
constraints, ordering, joins, and reviewer queries. Claims and transcript turns
are one-to-many records, so child tables express them without duplicated parent
rows. `fixed_rubric` is different: it is a versioned model-response snapshot
with optional dimensions and nested evidence, while deterministic queryable
aggregates already live in `interview_score`.

**Compatibility:** D34 supersedes D33 for request persistence. The previously
applied `scoring_input` column remains deprecated because migrations are
additive-only; the post-call pipeline populates the normalized tables directly,
and new code does not read or write the legacy column.

## D35 · Normalize per-question rubric assessments

**Chosen:** validated Gemini measurements are persisted one-to-one in
`question_rubric_assessment`, with typed score, label, quote, rationale, and
provenance columns. `FixedRubricAssessment` remains the in-memory Pydantic
response schema used to validate Gemini before insertion.

**Rejected:** continuing to write `question_instance.fixed_rubric` JSONB.

**Why:** the fixed v2 rubric is stable core product data. Recruiter explanation,
calibration, and score audits need ordinary constraints and direct queries over
individual measurements and evidence. Nested JSON remains appropriate at the
LLM boundary, but not as the canonical database representation.

**Compatibility:** D35 supersedes D34 for response persistence. New code does
not read or write either legacy JSONB column. Physical column removal is handled
outside these additive migrations after every environment has moved to the
normalized schema.

## D36 · Bounded parallel post-call answer scoring

**Chosen:** score completed questions concurrently with a default limit of four
Gemini calls. Preserve question order and persist only after the whole batch
succeeds.

**Rejected:** sequential per-question calls, which make post-call latency grow
linearly, and unbounded fan-out, which turns longer interviews into avoidable
quota spikes.

**Why:** question assessments are independent, but Gemini capacity is not.
Bounded concurrency captures most of the latency win while keeping retries and
rate limits tractable. Registry provenance and factual context flags are
attached by application code, not copied from model claims.

## D37 · One post-call scoring prompt per interview

**Chosen:** send all completed question packages in one `score-interview` call,
validate that every expected question id appears exactly once, then persist and
aggregate the complete response.

**Rejected:** D36's parallel per-question calls.

**Why:** the product owner prefers one auditable model invocation per interview,
lower request count, and direct cross-answer consistency context. The prompt
explicitly requires independent per-question scoring to limit halo effects.
One malformed response fails the interview scoring run without publishing a
partial leaderboard result; rerunning by job id is idempotent.

**Compatibility:** D37 supersedes D36. This is a new registry task and prompt
version, so its scores must be calibrated separately from `score-answer.v2`.

## D38 · Google for Jobs, not LinkedIn

**Chosen:** publish `JobPosting` JSON-LD on a server-rendered public page at
`/j/{job_id}`, discovered through `sitemap.xml`. Free, sanctioned, no gatekeeper.

**Rejected: LinkedIn.** Verified rather than assumed this time.
- The **Job Posting API** is not open — LinkedIn *"is currently not accepting
  new partnerships"* for it.
- **Apply Connect** (the Easy Apply to ATS pipe) requires Talent Solutions
  Partner status and is *"only available for incorporated companies, not
  individual developers"*, behind a signed agreement and a relationship manager.
- **Zapier cannot bridge it.** Its LinkedIn integration is Lead Gen Forms
  (requires Ads spend) and company-page updates. There are no job-posting
  triggers or actions. Zapier connects APIs; it cannot open one that is closed.

**Rejected: headless-browser automation of LinkedIn**, including the version
where the customer supplies their own credentials.

The scraping objection does go away in that design — applicants apply on our
form, so no third-party PII is harvested. What remains does not:

- LinkedIn's User Agreement prohibits automated access regardless of whose
  account. A customer can consent to *us* using their account; they cannot
  consent on LinkedIn's behalf to something LinkedIn forbids. That is precisely
  what **hiQ Labs lost on**: they won the famous CFAA ruling on public data and
  still took a $500,000 judgment, a permanent injunction, and an order to
  destroy all derived source code, on breach of contract. The company no
  longer exists.
- It requires storing LinkedIn passwords in **recoverable** form — they have to
  be replayed at login. That is a larger liability than anything else we hold,
  resumes included.
- Most business accounts have 2FA, which breaks the flow or forces us to ask
  for TOTP seeds, which is worse.
- Detection restricts **the customer's** account, not ours. Shipping a product
  whose failure mode is destroying a customer's LinkedIn access ends the
  relationship on the first incident.

**The decisive argument is not legal, it is arithmetic.** LinkedIn already
supports "Apply on company website": a recruiter posts the job and pastes our
apply URL. Applicants land on our form and upload a resume — exactly the flow
we wanted, with no integration at all. Automation would save the recruiter
roughly two minutes per posting. Two minutes is not worth our largest security
liability plus a ban risk aimed at customers.

**Implementation notes**
- Server-rendered, not SPA-injected. Google can run JavaScript, but its own
  guidance calls server-rendered the standard approach, and an unindexed job
  fails silently — there is no error to notice.
- `validThrough` is mandatory in practice: Google issues a **manual action
  removing every job on a domain** that accumulates stale undated postings.
  Jobs default to a 60-day expiry, and closing one expires it immediately.
- Closed jobs render `noindex` and drop out of the sitemap.
- The JD is recruiter-supplied text rendered into a public page, so it is
  escaped before being wrapped in HTML.
- `indexing_problems()` reports what would prevent indexing, so the recruiter
  learns from the UI rather than from traffic that never arrives.

**Needs a public URL.** None of this does anything on localhost.

---

## D39 · Verify claims from links candidates give us; never source strangers

**Chosen:** an ADK agent that checks a candidate's claims against the GitHub
profile **they put on their own application**. Verification, not sourcing.

**Rejected: crawling GitHub to find candidates.** GitHub's Acceptable Use
Policy, section 7, closes the API loophole explicitly:

> "You may not use information from the Service (whether scraped, **collected
> through our API**, or obtained otherwise) for spamming purposes, including for
> the purposes of sending unsolicited emails to users or selling personal
> information, **such as to recruiters, headhunters, and job boards**."

That is this product's exact use case. Using their API is the same violation as
scraping — they wrote the clause to cover both.

**Also rejected: fetching LinkedIn to verify employment.** Same wall as D31.
Their User Agreement prohibits automated access, and the candidate consenting to
*us* does not waive terms *they* agreed to.

**GDPR, separately:** building profiles from crawled data is processing personal
data. Article 14 requires notifying each person within a month, and it applies
to public data. Links a candidate hands you on an application are a different
basis entirely.

## The four verdicts

| Finding | Effect |
|---|---|
| `supported` — direct evidence for the claim | raises confidence |
| `related` — adjacent work in the same domain | raises it modestly |
| `contradicted` — evidence conflicts with the claim | lowers it |
| **`not_found` — nothing either way** | **changes nothing** |

`related` was added in prompt v3 because the other three lose real signal. A
claim about private work can **never** be `supported` — the artifact is not
public. But someone who has built a payment gateway of their own is a more
plausible author of one at work than someone with no payments code at all.
Collapsing that into `not_found` throws away corroboration.

It is corroboration, never proof, and the `detail` must convey strength: "a
200-line tutorial integration" and "300 commits over two years" are both
`related` to a work claim, and a recruiter needs to see which. The prompt also
guards against stretching it — a React todo app is not `related` to a claim
about distributed systems.

Absence of public evidence is not evidence of absence. Most professional work
lives in private company repositories, so penalising an empty GitHub punishes
people for where their best work happens to sit — usually behind an employer's
firewall.

The same logic is why LinkedIn verification would have been unfair even if it
were permitted: penalising an unverifiable employment claim hits people with no
LinkedIn, private profiles, stale profiles, or from regions where it is not
dominant.

`contradicted` is a deliberately high bar, and **prompt v2 narrowed it
further after a name-collision problem was spotted**.

A repository may only contradict a claim if **the candidate named that
repository**. Otherwise what was found is a *different artifact*, and a
different artifact cannot contradict anything.

The failure this prevents: someone builds a real payments service at work
(private, substantial) and also has a small personal `payment-gateway` repo
they wrote while learning. The names collide, the agent judges the work claim by
the hobby repo, and an honest candidate loses points for having practised. Given
how generic project names are — `chat-app`, `dashboard`, `job-portal` — this is
likely rather than hypothetical.

So the rule is now:

| Claim shape | Can it be contradicted? |
|---|---|
| Names a specific repo, and that repo is not what they described | yes |
| Work at a company, similar-sounding personal repo found | **never** — private work is not on GitHub by definition |
| A skill in general ("knows Kafka") | **never** — absence cannot disprove a skill |

Enforced in both stages: the agent prompt and the formatter, so a stray
`contradicted` cannot slip through the second pass either.

**Failures map to `not_found` too.** A rate limit, a renamed account, an
outage — the tools say so explicitly in their output, so the model cannot infer
a negative from a technical problem.

## Why this is the right ADK use

`question_builder` (D9) is a fixed pipeline: the trajectory never varies, only
the content does. Evidence gathering is genuinely agentic — each finding decides
the next call. A repo whose name matches a claimed technology is worth opening;
a two-commit fork is not. That is what tools and a model-driven trajectory are
for.

**Implementation notes**
- Budget of 12 tool calls, enforced in the tools themselves via session state.
  Hitting it is normal completion, not failure.
- ADK cannot combine `output_schema` with tools, so the agent explores freely
  and a second typed call structures its notes. Gemini's `response_schema`
  guarantees the shape rather than hoping for well-formed JSON.
- `httpx`, not `urllib`: urllib uses the OS trust store, which is absent on some
  Python installs and fails every HTTPS call. That looked exactly like a
  candidate having no GitHub profile.
- Evidence is passed to the screen as **context to reason about**, never as a
  score adjustment, so the recruiter sees the same findings and can trace a
  decision to the repository behind it.
- `GITHUB_TOKEN` is optional but wanted: unauthenticated is 60 requests/hour,
  which one candidate can exhaust.

**Proved itself on the first real run.** The screen had earlier rejected a
candidate partly for "Python absent from the resume". The agent found a 106 KB
FastAPI-and-PostgreSQL repository under a link that candidate had supplied.

## D40 · Fixed rubric per job, questions generated per candidate

**Supersedes D16.**

**Chosen:** the job carries competencies, BARS anchors and weights. The probes
that elicit them are written per candidate at invite time, from `job.rubric`
plus their parsed resume.

**Rejected:** one fixed question bank shared by every applicant (D16).

**Why the reversal.** D16 was right that a leaderboard needs an invariant. It
picked the wrong one. The invariant a leaderboard needs is **the scoring frame,
not the question wording**.

| Fixed per job | Generated per candidate |
|---|---|
| competencies | the probe that elicits each one |
| BARS anchors, 1-5 | the poison question |
| dimension weights | drawn from their resume + the JD |
| `rubric_version` | |

Three problems with a fixed bank, in the order they bite:

1. **It leaks.** A bank is posted online after a handful of candidates. Later
   applicants arrive rehearsed, and the scores keep looking reasonable while
   measuring preparation instead of ability.
2. **Generic questions have a signal ceiling.** "How have you used Kafka?" gets
   a textbook answer from anyone who read the docs. It cannot separate
   at-least-once notification delivery, where a duplicate is harmless, from
   exactly-once payment processing, where it is not. Those are different
   competencies wearing the same word.
3. **The leaderboard ranks interview performance.** If the questions do not
   reach what the candidate actually built, the score measures the wrong thing.

**What keeps scores comparable.** Two candidates are asked different questions
about the same competency and scored against byte-identical anchors. The model
writes the probe and tags a competency; **we** attach that competency's
dimensions by lookup in `intake/questions.py`. Asking the model to copy anchors
would eventually score one candidate against subtly different ones, which is the
exact failure this design exists to prevent.

**The constraint that makes it work — portable anchors.** An anchor must be
scorable without knowing which probe produced the answer.

- Portable: *"Explains a specific failure mode and how they handled it."*
- Not portable: *"Mentions idempotency keys"* — correct for payments, wrong for
  notifications, and it would mark the notification candidate down for a correct
  answer about their own system.

So no anchor may name a technology, vendor or pattern. That constraint lands
entirely on `qb/rubric-writer.v2.md` and is enforced by `qb/validator.v2.md`.
**Verified 2026-08-23** on a live build: 7 competencies, 105 anchors, zero
technology mentions; two contrasting resumes produced entirely different probes
with identical dimensions on all 7 shared competencies, and different poison
questions.

**Generation happens at invite, not at redeem.** The candidate never waits on a
model call after clicking their link, and a dropped connection rejoining gets
the identical set (D12).

**A generation failure never blocks the invite.** It is recorded on
`application.questions_error` and the invite goes out anyway. Lane 2 falls back
to the job-wide bank; an unsendable invite is worse than a late question set.

**The cost, stated plainly.** Nobody reviews 2,000 question sets. Today a
recruiter reads one bank and judges it; per-candidate they cannot. Quality
control moves onto the rubric — which *is* reviewable, and which is what
determines scores — plus the generation prompt. The questions themselves become
unreviewed. That is a real reduction in oversight, accepted knowingly.

**One poison question per candidate**, invented to fit their stack. A fixed one
leaks first, being the most memorable question in the interview. Still never
auto-rejects (hard rule 9).

---

## D41 · ElevenLabs REST is the interview voice provider

**Chosen:** synthesize interviewer speech with ElevenLabs
`eleven_flash_v2_5`, requesting raw 24 kHz mono PCM through the REST API and
feeding it into LiveKit's `AudioEmitter`.

**Rejected:** keeping Rumik as the active provider. Its account returned
`INSUFFICIENT_BALANCE`, so it could not complete the production-shaped browser
test. Also rejected adding the ElevenLabs SDK or LiveKit plugin: the existing
REST adapter needs neither dependency.

**Why:** a real Chrome run completed the introduction, ten scored questions,
candidate question period, closing, disconnect, deterministic scoring, and the
Lane 3 database publication. The provider returned playable PCM for every
interviewer turn.

**Tradeoff accepted:** the REST adapter is non-streaming. It is simpler and
works on networks where the WebSocket route may fail, but time-to-first-audio
is higher than a streaming adapter and streamed LLM text may produce multiple
short synthesis requests. Revisit streaming only if measured conversational
latency becomes unacceptable.

---

## D42 · The application owns interview flow; the LLM owns bounded conversation

**Chosen:** keep scored question order, delivery acknowledgement, answer
capture, follow-up count, completion, and early-exit classification in the
Python state machine. Candidate content cannot select a question or advance
the phase. The LLM is limited to the greeting, one candidate-question response,
and registered scoring tasks.

**Rejected:** one conversational prompt conducting the whole interview, and an
LLM intent-classification call before every turn.

**Why:** a generated interviewer can skip questions, interpret an interruption
as an answer, read internal follow-up guidance aloud, or obey candidate text.
Those failures corrupt the normalized Lane 2 → Lane 3 record. Another model
call per turn adds latency, provenance, failure, and nondeterminism where a
conservative explicit branch is sufficient.

- LiveKit's completed speech handle proves a question was delivered. An
  interrupted prompt is repeated and its overlapping candidate fragment is not
  scored.
- Clarification, explicit off-topic, prompt-injection, and short uncertainty
  responses are deterministic branches. Injection evidence is persisted at
  once. Unmatched answer text remains untrusted and never enters a system
  instruction.
- At most one configured, candidate-safe follow-up is allowed. Internal
  `follow_up_guidance` remains evaluator data and is never spoken.
- Live correctness may request the follow-up, but it gets two seconds before
  the deterministic shallow-answer rule continues the call.
- Completion requires every configured question to have a delivered prompt and
  a primary answer before the candidate-question period. Anything else keeps
  its captured data, becomes `abandoned`, and cannot publish an
  `interview_score`.
- The candidate may end at any time. The API deletes the media room immediately
  while the worker alone decides whether the final state is `completed` or
  `abandoned`.

**Tradeoff accepted:** phrase-based intent handling is deliberately
high-precision rather than pretending to understand every possible off-topic
answer. Unrecognized content is scored as an answer and should receive weak
evidence; it cannot redirect the state machine or reveal private context.

---

## Provenance of the original plan

The pre-repo architecture research was produced by a different model driving web
search subagents. The *structure* held up; several *specifics* did not — stale
model names, at least two miscited arXiv IDs the subagent itself flagged, vendor
marketing claims relayed as fact, and two "competitors" that turned out not to
be recruiting products. Anything from that plan that is not re-verified in this
repo should be treated as unverified. Do not put its figures in a pitch.
