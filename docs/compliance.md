# Compliance

Not optional and not deferrable — these obligations attach the moment a real
candidate uses the product, and consent cannot be collected retroactively.

## What must be true before launch

- **Human review on every rejection.** GDPR Art. 22 and NY AEDTA both require
  it. The integrity score is evidence for a reviewer, never an auto-reject.
- **Disclosure before the interview starts.** That AI conducts it, that audio is
  recorded, what is analysed, how long it is kept, and how to request deletion.
- **Explicit opt-in** for voice recording. Voice is biometric data under GDPR
  Art. 9 and Illinois BIPA.
- **Written retention policy**, enforced by an actual scheduled job, not a
  promise. BIPA damages are per-person.
- **Annual independent bias audit** (NY AEDTA), published.

## Where each obligation actually lives in the code

Promises in this file are worthless unless something enforces them. As of the
multi-tenancy rebuild:

| Obligation | Enforced by |
|---|---|
| Consent before processing | `apply()` checks it **before reading the file** — processing without consent is the violation, discarding the result afterwards does not undo it |
| A human reviews rejections | `POST /applications/{id}/decide`, which records `decided_by`, `decided_at`, `decision_note` |
| Rejections are contestable | Screen-rejected candidates stay in `rejected_screen`, visible and reversible — inviting from that list overrides the filter |
| Decisions are attributable | `screening_model_id` + `screening_prompt_version` on every application (D5) |
| Evidence, not assertion | `ScreeningDecision.evidence` is required — an unevidenced rejection is not defensible |
| One company cannot see another's candidates | Composite foreign keys (D25) and per-org candidates (D26) |

**Still unenforced:** retention windows below. Nothing deletes anything yet.

## Retention defaults

| Data | Window |
|---|---|
| Raw interview audio | 90 days |
| Transcripts | 12 months |
| Scores + provenance | 24 months |
| Integrity events | 24 months |

Show candidates their deletion date. It is cheap and it is the difference
between a product people trust and one they resent.

## Proctoring posture

Browser-only, no install, but every available signal applied to every
interview. Behavioural and content signals catch behaviour rather than binaries,
so they also catch a phone under the desk — not just one named tool.

Calibrate against diverse baselines. Latency and phrasing detectors flag
non-native speakers and neurodivergent candidates at higher rates, and a
false positive costs a real person a job. Human in the loop, always.

## Erasure vs. the company's record

These pull in opposite directions and the tension is worth naming before it
becomes urgent.

A candidate may demand deletion. A company needs its hiring record — who was
interviewed, why they were rejected — and this file requires decision records
for 24 months. Closed jobs keep everything (D29), which sharpens the conflict.

The standard resolution: **delete the personal data, keep the anonymised
decision record.** The company retains its funnel history and audit trail; the
person becomes unidentifiable in it.

Per-org candidates (D26) already make this tractable — PII is concentrated in
the `candidate` row rather than smeared across every org that person ever
applied to. `application` still holds `parsed_resume`, which is PII and would
need clearing too.

Not built. Worth building before the first real customer, not the first request.

## TODO

- [ ] Consent screen copy, per region
- [ ] Retention job — nothing currently deletes anything
- [ ] Candidate deletion request flow (see above)
- [ ] Bias audit plan
- [ ] Adverse-impact reporting per job — selection rates by group, which is what
      an AEDTA audit will actually ask for
