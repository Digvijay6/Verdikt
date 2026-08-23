# Scoring specification

The one place the formula lives. Do not inline it anywhere else — two copies
will disagree within a week.

## Per answer

Each answer is scored 0-100 on these dimensions:

- **Domain Technical Accuracy** — how correct and complete is the answer?
- **Project / Answer Depth** — how specific vs. generic is the answer?
- **Follow-up Resilience** — how well does the candidate hold up when drilled?
  (only scored if a follow-up was asked)

Plus two categorical labels per answer:

- **Ownership Level** — `full_owner` / `major_contributor` / `minor_contributor`
  / `unclear`. If `unclear`, cap `project_depth` at 49.
- **Consistency Label** — `consistent` / `vague` / `unverifiable` / `inflated`.
  Aggregated into `consistency_score` (see below).

Scale anchors and the judge's rules are in `llm/prompts/score-answer.v1.md`.

## Overall

    overall = w1 · mean(domain_technical_accuracy)
            + w2 · mean(project_depth)
            + w3 · mean(followup_resilience)
            + w4 · consistency_score

Weights shift by seniority:

| Dimension | Junior | Mid | Senior |
|---|---|---|---|
| Domain technical accuracy | 0.45 | 0.35 | 0.25 |
| Project depth | 0.20 | 0.30 | 0.35 |
| Follow-up resilience | 0.20 | 0.20 | 0.25 |
| Consistency | 0.15 | 0.15 | 0.15 |

Junior candidates often lack deep project history, so raw technical knowledge
carries more weight. Senior candidates are judged more on whether their claimed
experience holds up under scrutiny.

## Consistency score

    consistency_score = max(0, 100 - sum(penalties across all answers))

| Label | Penalty per instance |
|---|---|
| `consistent` | 0 |
| `vague` | -5 |
| `unverifiable` | -3 |
| `inflated` | -15 |

## Human review triggers

Flag `needs_human_review = true` if any of these occur, even if the composite
score is high:

- Any `inflated` consistency label on a claim central to the role
- `followup_resilience_score` below 40 on a resume-headline claim
- `ownership_level = unclear` on the candidate's flagship project
- Composite > 80 but built mostly from background questions, not
  technical/project

## Integrity penalty

Multiplicative, not additive, so cheat flags cannot be averaged away.
Applied after the composite and human-review checks.

Percentiles are within one job only. Never rank across jobs.

## Hybrid timing

- **During the call** — `score-answer-live`, correctness only, cheap model.
  Shown to the recruiter clearly marked provisional.
- **After the call** — two-pass. Pass 1 scores each question against the full
  rubric. Pass 2 scores holistically over the assembled dossier, not the raw
  transcript, which keeps the prompt bounded and surfaces cross-question
  patterns per-question scoring structurally cannot see.

The post-call result overwrites the live signal.

## Calibration — TODO before any real candidate

Scores are not portable across models or prompt versions. Same prompt,
different model, different distribution.

1. Hand-score 20-30 answers spanning the full 0-100 range.
2. Re-run that set on every model or prompt change.
3. If the distribution shifts, recalibrate or re-score affected candidates.
4. Every score row carries `model_id` and `prompt_version` — that is what
   makes step 3 possible.

## Poison questions

One question per interview references technology that does not exist. A model
confabulates a plausible answer; a real candidate says they do not know it.
Highest signal per hour of work in the whole anti-cheat plan, and it is a
prompt rather than a model. Rotate the fake names per job so they cannot be
shared between candidates.