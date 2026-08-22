# Setup

What each person needs before the repo runs. Roughly 30 minutes, plus DNS wait
time on one item.

## 0. Install

| Tool | Why |
|---|---|
| Docker Desktop | runs everything — `docker compose up` |
| Supabase CLI | **`npx supabase@latest <cmd>`** — no install needed |
| Node 20+ | only if running the frontend outside Docker |
| Python 3.12 or 3.13 | only if running the backend outside Docker |

Versions are pinned (`~=`) in `backend/pyproject.toml` and `frontend/package.json`
rather than left open, so all three of you resolve the same tree. Open ranges
produce bugs that reproduce for exactly one person.

## 1. Accounts and keys

Fill these into `.env` at the repo root (copy `.env.example`). **Only one
person needs to create these** — share the `.env` privately, never commit it.

### Supabase → `SUPABASE_*`

1. supabase.com → new project. Save the database password somewhere.
2. Settings → **API Keys**. Supabase renamed these — new projects show
   *publishable* and *secret* rather than *anon* and *service_role*:
   - Project URL → `SUPABASE_URL` and `VITE_SUPABASE_URL`
   - **Publishable key** (`sb_publishable_…`) → `VITE_SUPABASE_ANON_KEY`.
     Public by design.
   - **Secret key** (`sb_secret_…`) → `SUPABASE_SERVICE_KEY`. Bypasses every
     security rule — **server only, never in a `VITE_` variable.** Supabase
     now returns 401 if it is used from a browser, but do not rely on that.
3. **Leave `SUPABASE_JWT_SECRET` blank.** New projects sign session tokens with
   ES256 and the backend verifies them against the project's JWKS endpoint
   automatically. Only fill it in if your project still issues HS256 tokens —
   both paths are supported.
4. Storage → new bucket named **`resumes`**, **not public**.
5. Apply the schema:
   ```bash
   npx supabase@latest login
   npx supabase@latest link --project-ref <your-ref>
   npx supabase@latest db push          # asks for the database password
   ```

   Use `npx`, not Homebrew. `brew install supabase/tap/supabase` needs current
   Command Line Tools, which on macOS 26.x means a 7.4 GB OS update. `npx`
   fetches a prebuilt binary and avoids the whole problem.

   **Paste each key onto a single line.** A wrapped key breaks
   `docker compose` with `invalid environment variable`, and the error does not
   tell you which line.

### Gemini → `GEMINI_API_KEY`

aistudio.google.com → Get API key.

**Check how the hackathon issues credits first.** If they hand out a GCP
project with Vertex AI rather than an AI Studio key, the SDK needs different
configuration and we should switch before building further on it.

### LiveKit → `LIVEKIT_*`

cloud.livekit.io → new project → Settings → Keys. Needed for lane 2; the API
will not boot without the variables present, so put placeholders in if you are
only working on lane 1.

### Resend → `RESEND_API_KEY`

resend.com → API Keys.

**Start this one first — it has DNS lead time.** Until a domain is verified,
Resend only delivers to your own account email, so nobody else can receive an
interview invite. Domains → Add → add the DNS records at your registrar. For
demo purposes their test domain works, but the invite email is a core part of
the flow.

## 2. Run it

```bash
cp .env.example .env      # then fill it in
docker compose up         # api :8000, frontend :5173
```

- API docs: http://localhost:8000/docs
- App: http://localhost:5173

Lane 2 also needs the worker: `docker compose --profile voice up`

**Verified working:** both images build, 27 tests pass inside the container on
Python 3.12, the API serves OpenAPI, and Vite hot-reloads through the volume
mount. Placeholder credentials are enough to boot — you only need real ones
when something actually calls out.

Lane 2's LiveKit dependencies are a separate extra (`.[voice]`) so lanes 1 and
3 do not install an audio stack they never import. The compose `voice` profile
builds with it; `api` does not.

Useful:

```bash
docker compose run --rm --no-deps api python -m pytest tests/ -q   # tests
docker compose exec api bash                                       # shell in
docker compose build --no-cache api                                # clean rebuild
```

## 3. Verify it actually works

Structural tests pass already, but nothing has hit real Gemini or Supabase yet.
This is the first real check:

```bash
# 1. tables exist
supabase db push && echo "schema applied"

# 2. backend healthy
curl localhost:8000/health

# 3. create a job — this triggers the ADK question_builder
#    poll /intake/jobs until question_bank_status is "ready"

# 4. read the generated question bank end to end
```

That last step is the one that matters and cannot be automated. Are the BARS
anchors behaviourally observable? Would two people score the same answer the
same way? Lane 2 scores against those exact words, so a vague anchor produces
inconsistent scores that nothing downstream can repair.

## 4. Known lead-time items

- **Resend domain verification** — DNS propagation, start now
- **Gemini model IDs in `llm/registry.json` are unverified.** They came from
  documentation searches, not from a live API. Once you have a key, list the
  models actually available to your account and correct the registry. An exact
  model id is required; a wrong one fails at call time, not at startup.
- **Supabase free tier pauses after a week of inactivity.** Fine during the
  hackathon, worth knowing before a demo.
