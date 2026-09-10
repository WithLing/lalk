"""RNNoise suppression with format-preserving streaming resampling."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
import soxr
from pyrnnoise import RNNoise

from ..errors import AudioError, AudioFormatError, AudioStateError
from ..types import AudioChunk, AudioFormat

_RNNOISE_RATE = 48_000


class RNNoiseFilter:
    """Denoise mono PCM, preserving its sample rate with streaming resampling."""

    def __init__(self) -> None:
        self._format: AudioFormat | None = None
        self._rnnoise: RNNoise | None = None
        self._resampler_in: soxr.ResampleStream | None = None
        self._resampler_out: soxr.ResampleStream | None = None
        self._lock = asyncio.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._closed = False

    async def start(self, audio_format: AudioFormat) -> None:
        """Initialize the engine and resamplers for a mono input stream."""
        async with self._lock:
            if self._closed:
                raise AudioStateError("RNNoiseFilter has already been closed")
            if audio_format.channels != 1:
                raise AudioFormatError("RNNoiseFilter requires mono audio")
            if self._format is not None:
                if self._format != audio_format:
                    raise AudioFormatError("RNNoiseFilter input format cannot change")
                return
            executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="lalk-rnnoise"
            )
            try:
                future = asyncio.get_running_loop().run_in_executor(
                    executor, self._initialize, audio_format
                )
                await self._await_worker(future)
            except BaseException:
                await asyncio.to_thread(
                    executor.shutdown, wait=True, cancel_futures=True
                )
                self._release()
                raise
            self._executor = executor

    async def filter(self, chunk: AudioChunk) -> AudioChunk | None:
        """Process a chunk without resetting state at speech boundaries."""
        async with self._lock:
            if self._closed or self._executor is None:
                raise AudioStateError("RNNoiseFilter is not running")
            if chunk.format != self._format:
                raise AudioFormatError(
                    f"RNNoiseFilter requires {self._format!r}, "
                    f"received {chunk.format!r}"
                )
            if not chunk.data:
                return None
            future = asyncio.get_running_loop().run_in_executor(
                self._executor, self._filter, chunk
            )
            return await self._await_worker(future)

    async def close(self) -> None:
        """Finish any active worker and discard pending audio."""
        async with self._lock:
            self._closed = True
            executor = self._executor
            self._executor = None
            self._release()
            if executor is not None:
                await asyncio.to_thread(
                    executor.shutdown, wait=True, cancel_futures=True
                )

    async def _await_worker(self, future: asyncio.Future[Any]) -> Any:
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # Native processing must finish before the lifecycle lock is released.
            await asyncio.shield(future)
            raise

    def _initialize(self, audio_format: AudioFormat) -> None:
        try:
            self._rnnoise = RNNoise(sample_rate=_RNNOISE_RATE)
            # Warm up lazy model and frame-graph initialization before capture.
            list(self._rnnoise.denoise_chunk(np.zeros(480, dtype=np.int16)))
            if audio_format.sample_rate != _RNNOISE_RATE:
                self._resampler_in = soxr.ResampleStream(
                    audio_format.sample_rate,
                    _RNNOISE_RATE,
                    1,
                    dtype="float32",
                    quality="LQ",
                )
                self._resampler_out = soxr.ResampleStream(
                    _RNNOISE_RATE,
                    audio_format.sample_rate,
                    1,
                    dtype="float32",
                    quality="LQ",
                )
            self._format = audio_format
        except Exception as error:
            raise AudioError(f"Unable to initialize RNNoise: {error}") from error

    def _filter(self, chunk: AudioChunk) -> AudioChunk | None:
        assert self._rnnoise is not None
        samples = np.frombuffer(chunk.data, dtype="<i2")
        if self._resampler_in is not None:
            # Float resampling avoids SOXR's int16 dither; values retain PCM16
            # amplitude and are rounded/clipped before entering RNNoise.
            samples = self._resampler_in.resample_chunk(samples.astype(np.float32))
            samples = np.clip(np.rint(samples), -32768, 32767).astype(np.int16)
        if not samples.size:
            return None
        frames = [
            frame.reshape(-1)
            for _, frame in self._rnnoise.denoise_chunk(samples, partial=False)
        ]
        if not frames:
            return None
        samples = np.concatenate(frames)
        if self._resampler_out is not None:
            samples = self._resampler_out.resample_chunk(samples.astype(np.float32))
            samples = np.clip(np.rint(samples), -32768, 32767).astype(np.int16)
        if not samples.size:
            return None
        return AudioChunk(samples.astype("<i2", copy=False).tobytes(), chunk.format)

    def _release(self) -> None:
        if self._rnnoise is not None:
            self._rnnoise.reset()
        self._rnnoise = None
        self._resampler_in = None
        self._resampler_out = None
        self._format = None
