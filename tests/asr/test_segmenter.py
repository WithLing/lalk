import pytest

from lalk.asr import SpeechSegmenter
from lalk.audio import AudioChunk, AudioFormat, AudioFormatError
from lalk.vad import VADState

_FORMAT = AudioFormat(sample_rate=1_000, channels=1)


def _chunk(
    value: int, *, frames: int = 10, audio_format: AudioFormat = _FORMAT
) -> AudioChunk:
    data = value.to_bytes(2, "little", signed=True) * frames * audio_format.channels
    return AudioChunk(data, audio_format)


def test_rejects_negative_pre_roll() -> None:
    with pytest.raises(ValueError, match="pre_roll_ms"):
        SpeechSegmenter(pre_roll_ms=-1)


def test_emits_speech_with_bounded_pre_roll() -> None:
    segmenter = SpeechSegmenter(pre_roll_ms=20)

    assert segmenter.push(_chunk(1), VADState.SILENCE) is None
    assert segmenter.push(_chunk(2), VADState.SILENCE) is None
    assert segmenter.push(_chunk(3), VADState.SILENCE) is None
    assert segmenter.push(_chunk(4), VADState.SPEAKING) is None

    segment = segmenter.push(_chunk(5), VADState.SILENCE)

    assert segment == AudioChunk(
        _chunk(2).data + _chunk(3).data + _chunk(4).data + _chunk(5).data,
        _FORMAT,
    )
    assert segmenter.push(_chunk(6), VADState.SILENCE) is None


def test_collects_all_chunks_while_speaking() -> None:
    segmenter = SpeechSegmenter(pre_roll_ms=0)

    assert segmenter.push(_chunk(1), VADState.SPEAKING) is None
    assert segmenter.push(_chunk(2), VADState.SPEAKING) is None
    segment = segmenter.push(_chunk(3), VADState.SILENCE)

    assert segment == AudioChunk(
        _chunk(1).data + _chunk(2).data + _chunk(3).data,
        _FORMAT,
    )


def test_keeps_consecutive_segments_independent() -> None:
    segmenter = SpeechSegmenter(pre_roll_ms=10)

    segmenter.push(_chunk(1), VADState.SILENCE)
    segmenter.push(_chunk(2), VADState.SPEAKING)
    first = segmenter.push(_chunk(3), VADState.SILENCE)

    segmenter.push(_chunk(4), VADState.SILENCE)
    segmenter.push(_chunk(5), VADState.SPEAKING)
    second = segmenter.push(_chunk(6), VADState.SILENCE)

    assert first == AudioChunk(
        _chunk(1).data + _chunk(2).data + _chunk(3).data,
        _FORMAT,
    )
    assert second == AudioChunk(
        _chunk(4).data + _chunk(5).data + _chunk(6).data,
        _FORMAT,
    )


def test_reset_discards_unfinished_audio() -> None:
    segmenter = SpeechSegmenter(pre_roll_ms=10)
    segmenter.push(_chunk(1), VADState.SILENCE)
    segmenter.push(_chunk(2), VADState.SPEAKING)

    segmenter.reset()
    segmenter.push(_chunk(3), VADState.SILENCE)
    segmenter.push(_chunk(4), VADState.SPEAKING)
    segment = segmenter.push(_chunk(5), VADState.SILENCE)

    assert segment == AudioChunk(
        _chunk(3).data + _chunk(4).data + _chunk(5).data,
        _FORMAT,
    )


def test_rejects_format_changes_within_a_stream() -> None:
    segmenter = SpeechSegmenter()
    segmenter.push(_chunk(1), VADState.SILENCE)

    with pytest.raises(AudioFormatError, match="SpeechSegmenter requires"):
        segmenter.push(
            _chunk(2, audio_format=AudioFormat(sample_rate=2_000)),
            VADState.SILENCE,
        )


def test_reset_accepts_a_new_stream_format() -> None:
    segmenter = SpeechSegmenter()
    segmenter.push(_chunk(1), VADState.SILENCE)

    segmenter.reset()

    assert (
        segmenter.push(
            _chunk(2, audio_format=AudioFormat(sample_rate=2_000)),
            VADState.SILENCE,
        )
        is None
    )
