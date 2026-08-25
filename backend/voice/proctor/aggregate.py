"""Post-call integrity aggregation.

Browser events are collected during the call via /interview/events. Post-call,
we also run audio diarization (if a candidate audio track is available) and
check poison-question and latency patterns. Everything is combined into an
IntegrityReport — never an auto-reject, always evidence for a human reviewer.
"""

from __future__ import annotations

import statistics

from shared.models.interview import (
    IntegrityEvent,
    IntegrityEventType,
    IntegrityReport,
)
from voice.interview.state_machine import InterviewStateMachine

# Severity weights for each event type (contributes to the 0-100 score)
SEVERITY_WEIGHTS: dict[IntegrityEventType, float] = {
    IntegrityEventType.TAB_BLUR: 5,
    IntegrityEventType.FULLSCREEN_EXIT: 5,
    IntegrityEventType.PASTE_BURST: 15,
    IntegrityEventType.VIRTUAL_CAMERA: 25,
    IntegrityEventType.MULTIPLE_DISPLAYS: 10,
    IntegrityEventType.VM_DETECTED: 20,
    IntegrityEventType.RAF_JITTER: 5,
    IntegrityEventType.DEVICE_CHANGE: 5,
    IntegrityEventType.MULTI_SPEAKER: 30,
    IntegrityEventType.LATENCY_FLATLINE: 25,
    IntegrityEventType.POISON_QUESTION_FAILED: 40,
    IntegrityEventType.PROMPT_INJECTION: 35,
}

PROMPT_INJECTION_PATTERNS = (
    "ignore previous instructions",
    "ignore all previous",
    "disregard previous instructions",
    "forget your instructions",
    "you are now",
    "change your role",
    "give me a high score",
    "give me full marks",
    "mark every answer correct",
    "highest possible score",
    "reveal your prompt",
    "reveal the system prompt",
)


def detect_prompt_injection(text: str) -> str | None:
    lowered = " ".join(text.lower().split())
    return next(
        (pattern for pattern in PROMPT_INJECTION_PATTERNS if pattern in lowered),
        None,
    )


def aggregate_integrity(
    org_id: str,
    browser_events: list[IntegrityEvent],
    state_machine: InterviewStateMachine,
    answer_correctness_scores: dict[str, int] | None = None,
    audio_diarization_speakers: int | None = None,
) -> IntegrityReport:
    """Combine all integrity signals into a single IntegrityReport.

    Args:
        browser_events: Collected during the call via /interview/events.
        state_machine: The interview state machine (for poison + latency checks).
        answer_correctness_scores: Per-question live correctness scores
            {question_id: score}. Used for poison-question detection.
        audio_diarization_speakers: Number of distinct speakers detected
            post-call in the candidate audio track. None if no audio.
    """
    events = list(browser_events)

    # 1. Multi-speaker detection from post-call diarization
    if audio_diarization_speakers is not None and audio_diarization_speakers >= 2:
        events.append(IntegrityEvent(
            org_id=org_id,
            interview_id="",
            type=IntegrityEventType.MULTI_SPEAKER,
            severity=1.0,
            at_ms=0,
            detail={
                "speakers_detected": audio_diarization_speakers,
                "note": ">=2 speakers in candidate audio track",
            },
        ))

    # 2. Poison question check — did the candidate "know" non-existent tech?
    answer_correctness_scores = answer_correctness_scores or {}
    for turn in state_machine.get_all_turns():
        if turn.question.type.value == "poison":
            score = answer_correctness_scores.get(turn.question_id, 0)
            if score > 24:
                # Candidate claimed to know non-existent technology
                events.append(IntegrityEvent(
                    org_id=org_id,
                    interview_id="",
                    type=IntegrityEventType.POISON_QUESTION_FAILED,
                    severity=1.0,
                    at_ms=turn.answer_start_ms,
                    detail={
                        "question_id": turn.question_id,
                        "live_correctness": score,
                        "note": "Candidate claimed knowledge of "
                                "non-existent technology",
                    },
                ))

    # 3. Latency flatline — near-zero variance in Q-end → A-start latency
    latencies = [
        (t.answer_end_ms - t.answer_start_ms)
        for t in state_machine.get_all_turns()
        if t.answer_start_ms and t.answer_end_ms
    ]
    if len(latencies) >= 4:
        try:
            stdev = statistics.stdev(latencies)
            mean_latency = statistics.mean(latencies)
            # Flag if stdev is very low relative to mean (flatline)
            if mean_latency > 0 and stdev / mean_latency < 0.15:
                events.append(IntegrityEvent(
                    org_id=org_id,
                    interview_id="",
                    type=IntegrityEventType.LATENCY_FLATLINE,
                    severity=0.7,
                    at_ms=0,
                    detail={
                        "mean_latency_ms": mean_latency,
                        "stdev_ms": stdev,
                        "cv": stdev / mean_latency if mean_latency else 0,
                    },
                ))
        except statistics.StatisticsError:
            pass

    # 4. Prompt injection scan in candidate answers
    for turn in state_machine.get_all_turns():
        if pattern := detect_prompt_injection(turn.answer_text):
            events.append(IntegrityEvent(
                org_id=org_id,
                interview_id="",
                type=IntegrityEventType.PROMPT_INJECTION,
                severity=0.8,
                at_ms=turn.answer_start_ms,
                detail={
                    "question_id": turn.question_id,
                    "pattern": pattern,
                    "answer_snippet": turn.answer_text[:200],
                },
            ))

    # Compute the integrity score 0-100
    raw_score = sum(
        SEVERITY_WEIGHTS.get(e.type, 0) * e.severity for e in events
    )
    score = min(100, int(raw_score))

    # Summary
    if score < 30:
        status = "clear"
    elif score < 60:
        status = "review"
    else:
        status = "flagged"

    event_summaries = [
        f"{e.type.value} (severity {e.severity:.1f})" for e in events
    ]
    summary = (
        f"Integrity status: {status}. "
        f"{len(events)} event(s) detected. "
        f"Score: {score}/100. "
        f"Events: {', '.join(event_summaries) if event_summaries else 'none'}."
    )

    return IntegrityReport(
        score=score,
        events=events,
        summary=summary,
    )
