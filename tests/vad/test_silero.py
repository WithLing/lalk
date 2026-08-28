import asyncio
import threading
from collections import deque
from collections.abc import Iterable
from typing import Any

import numpy as np
import pytest

from lalk.audio import AudioChunk, AudioFormat
from lalk.vad import (
    VAD,
    SileroVAD,
    VADError,
    VADFormatError,
    VADState,
    VADStateError,
)

pytestmark = pytest.mark.asyncio


class _FakeDetector:
    def __init__(self, states: Iterable[bool] = ()) -> None:
        self.states = deque(states)
        self.calls: list[np.ndarray[Any, Any]] = []
        self.error: Exception | None = None
        self.state = False
        self.completed_segments = 0
        self.pop_calls = 0

    def accept_waveform(self, samples: np.ndarray[Any, Any]) -> None:
        self.calls.append(samples.copy())
        if self.error is not None:
            raise self.error
        if self.states:
            self.state = self.states.popleft()

    def is_speech_detected(self) -> bool:
        return self.state

    def empty(self) -> bool:
        return self.completed_segments == 0

    def pop(self) -> None:
        self.completed_segments -= 1
        self.pop_calls += 1


def _install_detector(
    monkeypatch: pytest.MonkeyPatch,
    states: Iterable[bool] = (),
) -> _FakeDetector:
    detector = _FakeDetector(states)
    monkeypatch.setattr(
        SileroVAD,
        "_load_detector",
        lambda _self, _input_format: detector,
    )
    return detector


def _chunk(samples: int, audio_format: AudioFormat, value: int = 0) -> AudioChunk:
    data = value.to_bytes(2, "little", signed=True) * samples * audio_format.channels
    return AudioChunk(data, audio_format)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"threshold": -0.1}, "threshold"),
        ({"threshold": 1.1}, "threshold"),
        ({"min_input_level": -0.1}, "min_input_level"),
        ({"min_input_level": 1.1}, "min_input_level"),
        ({"speech_start_ms": 0}, "speech_start_ms"),
        ({"speech_end_ms": 0}, "speech_end_ms"),
    ],
)
async def test_rejects_invalid_configuration(
    kwargs: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        SileroVAD(**kwargs)


async def test_implements_vad_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_detector(monkeypatch)
    vad: VAD = SileroVAD()

    assert vad.speech_start_confirmation_seconds == pytest.approx(0.2)
    assert vad.speech_end_confirmation_seconds == pytest.approx(0.3)
    await vad.start(AudioFormat(16_000))
    assert await vad.analyze(_chunk(320, AudioFormat(16_000))) is VADState.SILENCE
    await vad.close()


@pytest.mark.parametrize(
    "audio_format",
    [AudioFormat(16_000, 2), AudioFormat(8_000), AudioFormat(48_000)],
)
async def test_rejects_unsupported_audio_formats(audio_format: AudioFormat) -> None:
    vad = SileroVAD()

    with pytest.raises(VADFormatError):
        await vad.start(audio_format)

    await vad.close()


async def test_start_is_idempotent_for_the_same_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_detector(monkeypatch)
    vad = SileroVAD()
    audio_format = AudioFormat(16_000)

    await vad.start(audio_format)
    await vad.start(audio_format)

    with pytest.raises(VADStateError, match="another audio format"):
        await vad.start(AudioFormat(8_000))
    await vad.close()


async def test_converts_pcm_and_forwards_each_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = _install_detector(monkeypatch, [True])
    vad = SileroVAD()
    audio_format = AudioFormat(16_000)
    await vad.start(audio_format)

    data = b"\x00\x40\x00\xc0"
    state = await vad.analyze(AudioChunk(data, audio_format))

    assert state is VADState.SPEAKING
    assert len(detector.calls) == 1
    assert detector.calls[0].tolist() == [0.5, -0.5]
    await vad.close()


async def test_replaces_audio_below_minimum_input_level_with_silence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = _install_detector(monkeypatch)
    vad = SileroVAD(min_input_level=0.1)
    audio_format = AudioFormat(16_000)
    await vad.start(audio_format)

    await vad.analyze(_chunk(320, audio_format, value=3_277))

    assert np.count_nonzero(detector.calls[0]) == 0
    await vad.close()


async def test_forwards_audio_after_smoothed_input_level_reaches_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = _install_detector(monkeypatch)
    vad = SileroVAD(min_input_level=0.2)
    audio_format = AudioFormat(16_000)
    await vad.start(audio_format)

    for _ in range(3):
        await vad.analyze(_chunk(320, audio_format, value=16_384))

    assert np.count_nonzero(detector.calls[0]) == 0
    assert np.count_nonzero(detector.calls[1]) == 0
    assert detector.calls[2].tolist() == [0.5] * 320
    await vad.close()


async def test_returns_detector_speech_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_detector(monkeypatch, [False, True, True, False])
    vad = SileroVAD()
    audio_format = AudioFormat(16_000)
    await vad.start(audio_format)

    states = [await vad.analyze(_chunk(320, audio_format)) for _ in range(4)]

    assert states == [
        VADState.SILENCE,
        VADState.SPEAKING,
        VADState.SPEAKING,
        VADState.SILENCE,
    ]
    await vad.close()


async def test_discards_completed_sherpa_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detector = _install_detector(monkeypatch)
    detector.completed_segments = 2
    vad = SileroVAD()
    audio_format = AudioFormat(16_000)
    await vad.start(audio_format)

    await vad.analyze(_chunk(320, audio_format))

    assert detector.pop_calls == 2
    await vad.close()


async def test_empty_audio_keeps_current_state(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = _install_detector(monkeypatch)
    vad = SileroVAD()
    audio_format = AudioFormat(16_000)
    await vad.start(audio_format)

    assert await vad.analyze(AudioChunk(b"", audio_format)) is VADState.SILENCE
    assert detector.calls == []
    await vad.close()


async def test_analyze_requires_matching_running_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_detector(monkeypatch)
    vad = SileroVAD()

    with pytest.raises(VADStateError, match="not been started"):
        await vad.analyze(_chunk(320, AudioFormat(16_000)))

    await vad.start(AudioFormat(16_000))
    with pytest.raises(VADFormatError, match="requires"):
        await vad.analyze(_chunk(320, AudioFormat(8_000)))

    await vad.close()
    with pytest.raises(VADStateError, match="closed"):
        await vad.analyze(_chunk(320, AudioFormat(16_000)))


async def test_reports_model_load_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_load(_self: SileroVAD, _input_format: AudioFormat) -> None:
        raise RuntimeError("load failed")

    monkeypatch.setattr(SileroVAD, "_load_detector", fail_load)
    vad = SileroVAD()

    with pytest.raises(VADError, match="Unable to load"):
        await vad.start(AudioFormat(16_000))

    await vad.close()


async def test_reports_inference_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    detector = _install_detector(monkeypatch)
    detector.error = RuntimeError("inference failed")
    vad = SileroVAD()
    audio_format = AudioFormat(16_000)
    await vad.start(audio_format)

    with pytest.raises(VADError, match="Unable to analyze"):
        await vad.analyze(_chunk(320, audio_format))

    await vad.close()


async def test_inference_does_not_block_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()

    class BlockingDetector(_FakeDetector):
        def accept_waveform(self, samples: np.ndarray[Any, Any]) -> None:
            started.set()
            if not release.wait(timeout=2):
                raise RuntimeError("test inference timed out")
            super().accept_waveform(samples)

    detector = BlockingDetector()
    monkeypatch.setattr(
        SileroVAD,
        "_load_detector",
        lambda _self, _input_format: detector,
    )
    vad = SileroVAD()
    audio_format = AudioFormat(16_000)
    await vad.start(audio_format)

    analyzing = asyncio.create_task(vad.analyze(_chunk(320, audio_format)))
    assert await asyncio.to_thread(started.wait, 1)
    await asyncio.sleep(0)
    assert not analyzing.done()

    release.set()
    assert await analyzing is VADState.SILENCE
    await vad.close()


async def test_close_is_idempotent_and_prevents_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_detector(monkeypatch)
    vad = SileroVAD()

    await vad.close()
    await vad.close()

    with pytest.raises(VADStateError, match="already been closed"):
        await vad.start(AudioFormat(16_000))


async def test_bundled_model_analyzes_silence() -> None:
    vad = SileroVAD(speech_start_ms=32, speech_end_ms=32)
    audio_format = AudioFormat(16_000)
    await vad.start(audio_format)
    try:
        for _ in range(50):
            assert await vad.analyze(_chunk(320, audio_format)) is VADState.SILENCE
    finally:
        await vad.close()
