import asyncio
import ctypes
import threading
from typing import Any

import pytest

import lalk.audio._macos as macos_module
from lalk.audio import AudioChunk, AudioDeviceError, AudioFormatError
from lalk.audio._macos import MacOSVoiceProcessingBackend

pytestmark = pytest.mark.asyncio


class _FakeLibrary:
    def __init__(self) -> None:
        self.handle = 42
        self.started = False
        self.stopped = False
        self.destroyed = False
        self.start_result = 0
        self.capture_result = 2
        self.played_frames = 0
        self.queued_frames = 0
        self.wait_calls = 0
        self.write_sizes: list[int] = []
        self.error = b"native failure"
        self.read_started = threading.Event()
        self.release_read = threading.Event()
        self.block_reads = False
        self.write_started = threading.Event()
        self.release_write = threading.Event()
        self.block_writes = False

    def lalk_voice_io_create(self) -> int:
        return self.handle

    def lalk_voice_io_destroy(self, handle: int) -> None:
        assert handle == self.handle
        self.destroyed = True

    def lalk_voice_io_start(self, handle: int) -> int:
        assert handle == self.handle
        self.started = self.start_result == 0
        return self.start_result

    def lalk_voice_io_stop(self, handle: int) -> None:
        assert handle == self.handle
        self.stopped = True
        self.release_read.set()
        self.release_write.set()

    def lalk_voice_io_read_capture(
        self,
        handle: int,
        destination: Any,
        count: int,
        _timeout_ms: int,
    ) -> int:
        assert handle == self.handle
        self.read_started.set()
        if self.block_reads:
            self.release_read.wait(timeout=2)
            return -1
        if self.capture_result > 0:
            assert count >= 2
            destination[0] = 100
            destination[1] = -100
        return self.capture_result

    def lalk_voice_io_write_playback(
        self,
        handle: int,
        _source: Any,
        frame_count: int,
    ) -> int:
        assert handle == self.handle
        self.write_started.set()
        if self.block_writes:
            self.release_write.wait(timeout=2)
            return 0
        self.write_sizes.append(frame_count)
        self.queued_frames += frame_count
        return 1

    def lalk_voice_io_played_frames(self, handle: int) -> int:
        assert handle == self.handle
        return self.played_frames

    def lalk_voice_io_wait_playback(self, handle: int) -> int:
        assert handle == self.handle
        self.wait_calls += 1
        self.played_frames += self.queued_frames
        self.queued_frames = 0
        return 1

    def lalk_voice_io_interrupt_playback(self, handle: int) -> int:
        assert handle == self.handle
        self.queued_frames = 0
        self.release_write.set()
        return 0

    def lalk_voice_io_copy_last_error(
        self,
        handle: int,
        destination: Any,
        capacity: int,
    ) -> int:
        assert handle == self.handle
        data = self.error[: capacity - 1]
        ctypes.memmove(destination, data + b"\0", len(data) + 1)
        return len(data)


@pytest.fixture
def fake_library(
    monkeypatch: pytest.MonkeyPatch,
) -> _FakeLibrary:
    library = _FakeLibrary()
    monkeypatch.setattr(macos_module.sys, "platform", "darwin")
    monkeypatch.setattr(macos_module, "_load_library", lambda _path: library)
    return library


def _pcm(frames: int) -> bytes:
    return b"\x01\x00" * frames


async def test_voice_processing_capture_and_playback(
    fake_library: _FakeLibrary,
) -> None:
    audio = MacOSVoiceProcessingBackend(block_ms=20)
    await audio.start()
    capture = audio.capture()

    chunk = await anext(capture)
    await audio.write(AudioChunk(_pcm(1_000), audio.output_format))
    await audio.wait_for_playback()

    assert chunk == AudioChunk(b"d\x00\x9c\xff", audio.input_format)
    assert fake_library.write_sizes == [960, 40]
    assert audio.played_frames == 1_000
    assert fake_library.wait_calls == 1

    await capture.aclose()
    await audio.close()
    assert fake_library.stopped
    assert fake_library.destroyed


async def test_voice_processing_rejects_wrong_playback_format(
    fake_library: _FakeLibrary,
) -> None:
    audio = MacOSVoiceProcessingBackend(block_ms=20)
    await audio.start()

    with pytest.raises(AudioFormatError, match="Playback requires"):
        await audio.write(AudioChunk(_pcm(20), audio.input_format))

    await audio.close()


async def test_voice_processing_start_propagates_native_error(
    fake_library: _FakeLibrary,
) -> None:
    fake_library.start_result = -1
    audio = MacOSVoiceProcessingBackend(block_ms=20)

    with pytest.raises(AudioDeviceError, match="native failure"):
        await audio.start()

    assert fake_library.stopped
    assert fake_library.destroyed


async def test_voice_processing_close_unblocks_capture(
    fake_library: _FakeLibrary,
) -> None:
    fake_library.block_reads = True
    audio = MacOSVoiceProcessingBackend(block_ms=20)
    await audio.start()
    capture = audio.capture()
    pending = asyncio.create_task(anext(capture))
    assert await asyncio.to_thread(fake_library.read_started.wait, 1)

    await audio.close()

    with pytest.raises(StopAsyncIteration):
        await pending


async def test_voice_processing_interrupt_unblocks_playback(
    fake_library: _FakeLibrary,
) -> None:
    fake_library.block_writes = True
    audio = MacOSVoiceProcessingBackend(block_ms=20)
    await audio.start()
    playback = asyncio.create_task(
        audio.write(AudioChunk(_pcm(960), audio.output_format))
    )
    assert await asyncio.to_thread(fake_library.write_started.wait, 1)

    await audio.interrupt_playback()
    await playback

    assert audio.played_frames == 0
    await audio.close()
