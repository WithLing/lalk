import pytest

from lalk.audio import AudioChunk, AudioFormat
from lalk.vad import AdaptiveInputLevelGate, InputLevelGateMode, VADState

_FORMAT = AudioFormat(16_000)


def _chunk(value: int) -> AudioChunk:
    return AudioChunk(value.to_bytes(2, "little", signed=True) * 320, _FORMAT)


def _observe(
    gate: AdaptiveInputLevelGate,
    chunk: AudioChunk,
    *,
    state: VADState = VADState.SILENCE,
    adapt: bool = True,
) -> AudioChunk:
    filtered, level_db = gate.filter(
        chunk,
        speaking=state is VADState.SPEAKING,
    )
    gate.observe(
        level_db=level_db,
        duration_seconds=chunk.duration_seconds,
        state=state,
        adapt=adapt,
    )
    return filtered


def _bootstrap(gate: AdaptiveInputLevelGate, *, value: int = 1_000) -> None:
    for _ in range(25):
        _observe(gate, _chunk(value))


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_rejects_invalid_minimum_level(value: float) -> None:
    with pytest.raises(ValueError, match="minimum_level"):
        AdaptiveInputLevelGate(minimum_level=value)


def test_passes_audio_until_a_quiet_bootstrap_window_completes() -> None:
    gate = AdaptiveInputLevelGate()
    quiet = _chunk(1_000)

    for _ in range(24):
        assert _observe(gate, quiet).data == quiet.data

    _observe(gate, quiet)
    below_start_threshold = _chunk(2_000)
    assert _observe(gate, below_start_threshold).data == bytes(
        len(below_start_threshold.data)
    )


def test_exposes_the_current_gate_threshold_and_decision() -> None:
    gate = AdaptiveInputLevelGate()
    _bootstrap(gate)

    gate.filter(_chunk(2_000), speaking=False)

    status = gate.status
    assert status is not None
    assert status.mode is InputLevelGateMode.NORMAL
    assert status.noise_floor_db is not None
    assert status.threshold_db == pytest.approx(status.noise_floor_db + 7.0)
    assert status.passed is False


def test_bootstrap_median_ignores_initial_device_zeroes() -> None:
    gate = AdaptiveInputLevelGate()

    for _ in range(10):
        _observe(gate, _chunk(0))
    for _ in range(15):
        _observe(gate, _chunk(1_000))

    below_start_threshold = _chunk(1_500)
    assert _observe(gate, below_start_threshold).data == bytes(
        len(below_start_threshold.data)
    )


def test_speech_restarts_an_incomplete_bootstrap_window() -> None:
    gate = AdaptiveInputLevelGate()
    quiet = _chunk(1_000)

    for _ in range(20):
        _observe(gate, quiet)
    _observe(gate, _chunk(8_000), state=VADState.SPEAKING)
    for _ in range(5):
        _observe(gate, quiet)

    candidate = _chunk(2_000)
    assert _observe(gate, candidate).data == candidate.data


def test_uses_a_lower_threshold_while_speech_is_active() -> None:
    start_gate = AdaptiveInputLevelGate()
    continuation_gate = AdaptiveInputLevelGate()
    _bootstrap(start_gate)
    _bootstrap(continuation_gate)
    candidate = _chunk(7_000)

    filtered_start, _ = start_gate.filter(candidate, speaking=False)
    filtered_continuation, _ = continuation_gate.filter(candidate, speaking=True)

    assert filtered_start.data == bytes(len(candidate.data))
    assert filtered_continuation.data == candidate.data


def test_uses_the_noise_floor_as_start_threshold_during_playback() -> None:
    normal_gate = AdaptiveInputLevelGate()
    playback_gate = AdaptiveInputLevelGate()
    _bootstrap(normal_gate)
    _bootstrap(playback_gate)
    candidate = _chunk(1_200)

    filtered_normal, _ = normal_gate.filter(
        candidate,
        speaking=False,
    )
    filtered_playback, _ = playback_gate.filter(
        candidate,
        speaking=False,
        playback_active=True,
    )

    assert filtered_normal.data == bytes(len(candidate.data))
    assert filtered_playback.data == candidate.data


def test_does_not_learn_during_playback() -> None:
    gate = AdaptiveInputLevelGate()
    _bootstrap(gate)

    for _ in range(200):
        _observe(gate, _chunk(10_000), adapt=False)
    for _ in range(25):
        gate.filter(_chunk(1_000), speaking=False)

    candidate = _chunk(7_000)
    filtered, _ = gate.filter(candidate, speaking=False)
    assert filtered.data == bytes(len(candidate.data))


def test_limits_upward_learning_during_a_sudden_level_change() -> None:
    gate = AdaptiveInputLevelGate()
    _bootstrap(gate)

    for _ in range(150):
        _observe(gate, _chunk(4_000))

    candidate = _chunk(7_000)
    filtered, _ = gate.filter(candidate, speaking=False)
    assert filtered.data == candidate.data
