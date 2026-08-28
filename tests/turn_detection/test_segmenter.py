import pytest

from lalk.audio import AudioChunk, AudioFormat, AudioFormatError
from lalk.turn_detection import SemanticTurnSegmenter
from lalk.vad import VADState

_FORMAT = AudioFormat(1_000)


def _chunk(value: int) -> AudioChunk:
    return AudioChunk(value.to_bytes(2, "little", signed=True) * 10, _FORMAT)


def test_keeps_one_turn_across_an_incomplete_pause() -> None:
    segmenter = SemanticTurnSegmenter(pre_roll_ms=10)

    segmenter.push(_chunk(1), VADState.SILENCE)
    started = segmenter.push(_chunk(2), VADState.SPEAKING)
    first_pause = segmenter.push(_chunk(3), VADState.SILENCE).pause
    segmenter.push(_chunk(4), VADState.SILENCE)
    resumed = segmenter.push(_chunk(5), VADState.SPEAKING)
    second_pause = segmenter.push(_chunk(6), VADState.SILENCE).pause

    assert started.started
    assert started.started_audio == AudioChunk(
        _chunk(1).data + _chunk(2).data,
        _FORMAT,
    )
    assert resumed.resumed
    assert first_pause is not None
    assert second_pause is not None
    assert segmenter.finalize(first_pause.id) is None
    assert segmenter.finalize(second_pause.id) == AudioChunk(
        b"".join(_chunk(value).data for value in range(1, 7)),
        _FORMAT,
    )


def test_finalizes_the_pause_snapshot_without_later_waiting_silence() -> None:
    segmenter = SemanticTurnSegmenter(pre_roll_ms=0)

    segmenter.push(_chunk(1), VADState.SPEAKING)
    pause = segmenter.push(_chunk(2), VADState.SILENCE).pause
    segmenter.push(_chunk(3), VADState.SILENCE)

    assert pause is not None
    assert segmenter.finalize(pause.id) == AudioChunk(
        _chunk(1).data + _chunk(2).data,
        _FORMAT,
    )


def test_rejects_format_changes_until_reset() -> None:
    segmenter = SemanticTurnSegmenter()
    segmenter.push(_chunk(1), VADState.SILENCE)

    with pytest.raises(AudioFormatError, match="SemanticTurnSegmenter requires"):
        segmenter.push(AudioChunk(b"\x00\x00", AudioFormat(2_000)), VADState.SILENCE)

    segmenter.reset()
    segmenter.push(AudioChunk(b"\x00\x00", AudioFormat(2_000)), VADState.SILENCE)
