# Scoring specification

The one place the formula lives. Do not inline it anywhere else — two copies
will disagree within a week.

## Per answer

Each answer is scored 1-5 on weighted dimensions defined by its question
template. Weights are re-normalised at aggregation so a missing dimension never
silently distorts the total.

    Q_i = Σ(w_k · d_ik) / Σ(w_k)

Scale anchors and the judge's rules are in `llm/prompts/score-answer.v1.md`.

## Overall

    overall = 0.55 · mean(Q_i) + 0.30 · holistic + 0.15 · role_fit

Then, in order:

1. **Hard gate** — any `must_have` question scoring ≤2 on correctness caps
   `overall` at 2.5. Stops a strong communicator averaging out a fundamental
   miss.
2. **Integrity penalty** — multiplicative, not additive, so cheat flags cannot
   be averaged away.

Percentiles are within one job only. Never rank across jobs: different rubrics,
different weights, sometimes different models.

## Hybrid timing

- **During the call** — `score-answer-live`, correctness only, cheap model.
  Shown to the recruiter clearly marked provisional.
- **After the call** — two-pass. Pass 1 scores each question against the full
  rubric. Pass 2 scores holistically over the assembled dossier, not the raw
  transcript, which keeps the prompt bounded and surfaces cross-question
  patterns per-question scoring structurally cannot see.

The post-call result overwrites the live signal.

## Calibration — TODO before any real candidate

Scores are not portable across models or prompt versions. Same prompt, different
model, different distribution.

1. Hand-score 20-30 answers spanning the full 1-5 range.
2. Re-run that set on every model or prompt change.
3. If the distribution shifts, recalibrate or re-score affected candidates.
4. Every score row already carries `model_id` and `prompt_version` — that is
   what makes step 3 possible.

Cheap to build now, impossible to retrofit.

## Poison questions

One question per interview references technology that does not exist. A model
confabulates a plausible answer; a real candidate says they do not know it.
Highest signal per hour of work in the whole anti-cheat plan, and it is a
prompt rather than a model. Rotate the fake names per job so they cannot be
shared between candidates.
