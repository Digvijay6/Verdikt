from voice.agent import _relative_ms, _worker_options


def test_worker_allows_postcall_scoring_to_finish_during_shutdown():
    options = _worker_options()

    assert options.shutdown_process_timeout == 180.0


def test_transcript_timestamps_are_relative_to_the_interview_start():
    assert _relative_ms(started_at_ms=1_787_589_081_000, now_ms=1_787_589_326_857) == 245_857
