# Interview scoring rubric v2

This is the authoritative scoring specification. Gemini extracts anchored
measurements and evidence; `backend/shared/interview_scoring.py` performs all
caps, penalties, weighting, and review triggers deterministically.

## Per-answer measurements

Every applicable fixed dimension is scored from 0 to 100. A dimension that is
not applicable is `null`, never zero. Every score must be supported by a
verbatim transcript quote and rationale in the answer's dimension evidence.

### Domain technical accuracy

| Score | Band | Anchor |
|---|---|---|
| 90-100 | Expert | Fully correct, precise, complete, and covers relevant edge cases. |
| 70-89 | Strong | Correct and mostly complete with only minor gaps. |
| 50-69 | Adequate | Core idea is correct but shallow or missing practical nuance. |
| 25-49 | Weak | Partly correct with misconceptions or rehearsed understanding. |
| 0-24 | Poor | Materially wrong, does not answer, or admits no knowledge. |

### Project or answer depth

| Score | Band | Anchor |
|---|---|---|
| 90-100 | Highly specific | Exact numbers, tools, versions, timeframes, constraints, and cause-and-effect. |
| 70-89 | Specific | Concrete details forming a mostly clear picture. |
| 50-69 | Generic with detail | Explains what happened, with little why or how. |
| 25-49 | Generic | Buzzword-heavy and transferable to almost any project. |
| 0-24 | Empty | Restates the question or provides no substantive content. |

### Ownership level

| Label | Meaning |
|---|---|
| `full_owner` | Designed, built, and made key decisions solo or as clear lead. |
| `major_contributor` | Owned a significant piece and made some decisions. |
| `minor_contributor` | Executed assigned work with limited decision-making. |
| `unclear` | Individual contribution cannot be separated from "we" claims. |

If ownership is still `unclear` after a direct follow-up, that answer's project
depth is capped at 49 before aggregation.

### Follow-up resilience

This score is present only when a direct follow-up was asked.

| Score | Band | Anchor |
|---|---|---|
| 90-100 | Rock solid | Adds new, consistent detail and can go deeper. |
| 70-89 | Holds up | Answers correctly with no meaningful contradiction. |
| 50-69 | Shaky | Repeats the original claim without adding depth. |
| 25-49 | Struggles | Becomes vague, hedges, or partly contradicts the claim. |
| 0-24 | Collapses | Cannot answer, contradicts the claim, or disowns the work. |

### Consistency

| Label | Penalty |
|---|---:|
| `consistent` | 0 |
| `vague` | 5 |
| `unverifiable` | 3 |
| `inflated` | 15 |

```text
consistency_score = max(0, 100 - sum(all answer penalties))
```

`unverifiable` is not dishonesty. It is a small comparability penalty and a
human-review signal only when another explicit rule says so.

## Interview aggregation

Technical accuracy, depth, and follow-up resilience are the arithmetic means of
their applicable per-answer scores. Missing dimensions are omitted and the
remaining seniority weights are re-normalized.

| Dimension | Junior | Mid-level | Senior |
|---|---:|---:|---:|
| Technical accuracy | 0.45 | 0.35 | 0.25 |
| Project depth | 0.20 | 0.30 | 0.35 |
| Follow-up resilience | 0.20 | 0.20 | 0.25 |
| Consistency | 0.15 | 0.15 | 0.15 |

```text
composite_score = sum(present_component * seniority_weight)
                  / sum(present_seniority_weights)
```

At least one skill component must be present; consistency alone cannot produce
a candidate score.

A failed must-have gate retains the existing product rule: final
`composite_score` is capped at 37.5, equivalent to 2.5 on the legacy scale, and
the result requires human review.

The old `overall` field remains for compatibility only:

```text
overall = 1 + 4 * (composite_score / 100)
```

New leaderboards rank on `composite_score`. Old v1 results without it fall back
to their converted `overall` value.

## Human review triggers

`needs_human_review` is true when any of these apply:

1. An `inflated` consistency label is attached to a central role claim.
2. Follow-up resilience is below 40 for a resume headline claim.
3. Ownership is `unclear` for the flagship project.
4. Composite is above 80 and at least 75% of scored answers are background
   questions. The 75% threshold is the operational definition of "almost
   entirely" and must not be changed silently.
5. A must-have hard gate was applied.

Insights additionally flags integrity scores of 60 or above and every rejection
recommendation. These are review requirements, not scoring penalties. Integrity
never causes automatic rejection.

## Hybrid timing

- During the call, `score-answer-live` provides a provisional correctness-only
  signal for adaptive follow-ups.
- After the call, `score-answer.v2` produces per-answer measurements and
  evidence. The deterministic aggregator creates the final composite and review
  reasons. The post-call result replaces the live signal.
- `score-holistic` may produce narrative strengths and concerns for recruiter
  explanation, but it does not alter the v2 composite.

## Calibration required before real candidates

1. Hand-score 20-30 answers spanning the full 0-100 range.
2. Include at least one strong hire, weak hire, and borderline transcript.
3. Re-run the set after every model, prompt, anchor, or weighting change.
4. Adjust seniority weights, not anchor meanings, when distributions drift.
5. Re-score affected candidates when provenance differs.

Every answer persists `model_id` and `prompt_version`; every interview persists
`rubric_version`. Scores with different provenance must not be silently treated
as calibrated equivalents.

## Two things are called a rubric — they are not the same thing

| | `job.rubric` (lane 1) | this document (lane 3) |
|---|---|---|
| What | competencies with BARS anchors, 1-5 | fixed dimensions, 0-100 |
| Scope | per job, built by `question_builder` | the whole product, one spec |
| Varies | yes, by role | no, ever |
| Carried on | each `Question.dimensions` | `interview_scoring.py` |

`job.rubric` is role-specific: what this job needs and what a 4 looks like for
it. This document is the aggregation that turns any set of anchored measurements
into one comparable number. A job's rubric changing bumps `rubric_version`; this
document changing bumps the scoring version and requires recalibration.

Since D35 the questions differ between candidates while the anchors do not.
Nothing here changes as a result — anchored measurement and deterministic
aggregation both operate on `Question.dimensions`, which still arrive in the
shape they always did. But calibration step 3 now has one more trigger worth
naming: **a change to `candidate-questions` is an anchor-affecting change**,
because it changes what candidates are asked to demonstrate against those
anchors, even though the anchors themselves are untouched.
