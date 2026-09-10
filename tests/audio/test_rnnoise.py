import asyncio
import threading

import numpy as np
import pytest
import soxr

from lalk.audio import (
    AudioChunk,
    AudioError,
    AudioFormat,
    AudioFormatError,
    AudioStateError,
)
from lalk.audio.filters import RNNoiseFilter

pytestmark = pytest.mark.asyncio


async def _denoise(samples: np.ndarray, rate: int, sizes: list[int]) -> np.ndarray:
    engine = RNNoiseFilter()
    audio_format = AudioFormat(rate)
    blocks = []
    offset = 0
    index = 0
    await engine.start(audio_format)
    try:
        while offset < samples.size:
            size = sizes[index % len(sizes)]
            chunk = AudioChunk(samples[offset : offset + size].tobytes(), audio_format)
            result = await engine.filter(chunk)
            if result is not None:
                assert result.format == audio_format
                blocks.append(np.frombuffer(result.data, dtype="<i2"))
            offset += size
            index += 1
    finally:
        await engine.close()
    return np.concatenate(blocks)


@pytest.mark.parametrize("rate", [16_000, 48_000])
async def test_real_rnnoise_preserves_stream_across_chunk_boundaries(rate: int) -> None:
    samples = np.random.default_rng(42).integers(-2000, 2000, rate * 3, dtype=np.int16)
    regular = await _denoise(samples, rate, [rate // 50])
    irregular = await _denoise(samples, rate, [1, 137, 811, 42, 999])

    # Chunk boundaries must not reset the recurrent model or resampler history.
    np.testing.assert_array_equal(irregular, regular)
    assert 0 <= samples.size - regular.size < rate // 10
    assert np.sqrt(np.mean(regular[rate:].astype(float) ** 2)) < 1000


async def test_real_rnnoise_has_bounded_streaming_delay() -> None:
    engine = RNNoiseFilter()
    audio_format = AudioFormat(16_000)
    await engine.start(audio_format)
    total_out = 0
    deficits = []
    try:
        for index in range(1000):
            result = await engine.filter(AudioChunk(bytes(640), audio_format))
            if result is not None:
                assert not any(result.data)
                total_out += result.frame_count
            if index >= 100:
                deficits.append((index + 1) * 320 - total_out)
        assert min(deficits) >= 0
        assert max(deficits) < 1600
        assert abs(deficits[-1] - deficits[0]) < 640
    finally:
        await engine.close()


async def test_48k_skips_resamplers_and_buffers_partial_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_resampler(*args: object, **kwargs: object) -> None:
        pytest.fail("48 kHz must not create a resampler")

    monkeypatch.setattr(soxr, "ResampleStream", unexpected_resampler)
    engine = RNNoiseFilter()
    audio_format = AudioFormat(48_000)
    await engine.start(audio_format)
    try:
        assert await engine.filter(AudioChunk(b"", audio_format)) is None
        assert await engine.filter(AudioChunk(bytes(200), audio_format)) is None
        result = await engine.filter(AudioChunk(bytes(760), audio_format))
        assert result == AudioChunk(bytes(960), audio_format)
    finally:
        await engine.close()


async def test_filter_rejects_wrong_format_and_closed_use() -> None:
    engine = RNNoiseFilter()
    with pytest.raises(AudioFormatError, match="mono"):
        await engine.start(AudioFormat(16_000, 2))
    await engine.start(AudioFormat(16_000))
    await engine.start(AudioFormat(16_000))
    with pytest.raises(AudioFormatError, match="cannot change"):
        await engine.start(AudioFormat(48_000))
    with pytest.raises(AudioFormatError, match="requires"):
        await engine.filter(AudioChunk(bytes(960), AudioFormat(48_000)))
    await engine.close()
    await engine.close()
    with pytest.raises(AudioStateError, match="not running"):
        await engine.filter(AudioChunk(bytes(640), AudioFormat(16_000)))
    with pytest.raises(AudioStateError, match="closed"):
        await engine.start(AudioFormat(16_000))


async def test_initialization_failure_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("resampler initialization failed")

    monkeypatch.setattr(soxr, "ResampleStream", fail)
    engine = RNNoiseFilter()
    with pytest.raises(AudioError, match="Unable to initialize RNNoise"):
        await engine.start(AudioFormat(16_000))
    await engine.close()


async def test_cancelled_processing_finishes_before_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = RNNoiseFilter()
    await engine.start(AudioFormat(16_000))
    started = threading.Event()
    release = threading.Event()
    actions = []
    worker_thread = []
    original_release = engine._release

    def blocking_filter(chunk: AudioChunk) -> AudioChunk:
        worker_thread.append(threading.get_ident())
        started.set()
        assert release.wait(5)
        actions.append("processed")
        return chunk

    def close_resources() -> None:
        actions.append("closed")
        original_release()

    monkeypatch.setattr(engine, "_filter", blocking_filter)
    monkeypatch.setattr(engine, "_release", close_resources)
    process = asyncio.create_task(
        engine.filter(AudioChunk(bytes(640), AudioFormat(16_000)))
    )
    closing = None
    try:
        assert await asyncio.to_thread(started.wait, 2)
        assert worker_thread[0] != threading.get_ident()
        process.cancel()
        closing = asyncio.create_task(engine.close())
        await asyncio.sleep(0)
        assert not process.done()
        assert not closing.done()
        assert actions == []
    finally:
        release.set()
        results = await asyncio.gather(process, return_exceptions=True)
        if closing is not None:
            await closing
        else:
            await engine.close()
    assert isinstance(results[0], asyncio.CancelledError)
    assert actions == ["processed", "closed"]


async def test_cancelled_start_releases_worker_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = RNNoiseFilter()
    started = threading.Event()
    release = threading.Event()
    initialize = engine._initialize

    def blocking_initialize(audio_format: AudioFormat) -> None:
        started.set()
        assert release.wait(5)
        initialize(audio_format)

    monkeypatch.setattr(engine, "_initialize", blocking_initialize)
    start = asyncio.create_task(engine.start(AudioFormat(16_000)))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        start.cancel()
        await asyncio.sleep(0)
        assert not start.done()
    finally:
        release.set()
        results = await asyncio.gather(start, return_exceptions=True)
        await engine.close()
    assert isinstance(results[0], asyncio.CancelledError)
    assert engine._rnnoise is None
    assert engine._executor is None
