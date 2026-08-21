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

## TODO

- [ ] Consent screen copy, per region
- [ ] Retention job
- [ ] Candidate deletion request flow
- [ ] Bias audit plan
