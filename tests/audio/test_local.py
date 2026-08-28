import asyncio
import threading
from collections.abc import Callable
from typing import Any

import pytest

import lalk.audio._portaudio as portaudio_module
import lalk.audio.local as local_module
from lalk.audio import (
    AudioChunk,
    AudioDeviceError,
    AudioFormat,
    AudioFormatError,
    AudioIO,
    AudioStateError,
    LocalAudio,
)

pytestmark = pytest.mark.asyncio


class _FakeStatus:
    def __bool__(self) -> bool:
        return False


class _FakeStream:
    def __init__(
        self,
        *,
        channels: int,
        callback: Callable[..., None] | None = None,
        finished_callback: Callable[[], None] | None = None,
        **_: Any,
    ) -> None:
        self.channels = channels
        self.callback = callback
        self.finished_callback = finished_callback
        self.active = False
        self.start_calls = 0
        self.stop_calls = 0
        self.abort_calls = 0
        self.close_calls = 0
        self.fail_start = False
        self.fail_stop = False

    def start(self) -> None:
        if self.fail_start:
            raise RuntimeError("start failed")
        self.start_calls += 1
        self.active = True

    def stop(self) -> None:
        if self.fail_stop:
            raise RuntimeError("stop failed")
        self.stop_calls += 1
        self.active = False

    def abort(self) -> None:
        self.abort_calls += 1
        self.active = False

    def close(self) -> None:
        self.close_calls += 1
        self.active = False


class _FakeInputStream(_FakeStream):
    def emit(self, data: bytes) -> None:
        if self.callback is None:
            raise RuntimeError("input callback is unavailable")
        frames = len(data) // (self.channels * 2)
        self.callback(data, frames, None, _FakeStatus())

    def finish_unexpectedly(self) -> None:
        self.active = False
        if self.finished_callback is None:
            raise RuntimeError("finished callback is unavailable")
        self.finished_callback()


class _FakeOutputStream(_FakeStream):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.writes: list[bytes] = []
        self.write_started = threading.Event()
        self._write_allowed = threading.Event()
        self._write_allowed.set()
        self.fail_write = False
        self.fail_abort = False

    def pause_writes(self) -> None:
        self.write_started.clear()
        self._write_allowed.clear()

    def resume_writes(self) -> None:
        self._write_allowed.set()

    def write(self, data: bytes) -> None:
        if self.fail_write:
            raise RuntimeError("write failed")
        self.write_started.set()
        if not self._write_allowed.wait(timeout=5):
            raise RuntimeError("fake output write timed out")
        self.writes.append(bytes(data))

    def abort(self) -> None:
        if self.fail_abort:
            raise RuntimeError("abort failed")
        super().abort()


class _FakeSoundDevice:
    def __init__(self) -> None:
        self.input_streams: list[_FakeInputStream] = []
        self.output_streams: list[_FakeOutputStream] = []
        self.fail_output_start = False

    def check_input_settings(self, **_: Any) -> None:
        pass

    def check_output_settings(self, **_: Any) -> None:
        pass

    def RawInputStream(self, **kwargs: Any) -> _FakeInputStream:
        stream = _FakeInputStream(**kwargs)
        self.input_streams.append(stream)
        return stream

    def RawOutputStream(self, **kwargs: Any) -> _FakeOutputStream:
        stream = _FakeOutputStream(**kwargs)
        stream.fail_start = self.fail_output_start
        self.output_streams.append(stream)
        return stream


class _FailingVoiceProcessingBackend:
    INPUT_FORMAT = AudioFormat(16_000)
    OUTPUT_FORMAT = AudioFormat(48_000)

    def __init__(self, *, block_ms: int) -> None:
        self.block_ms = block_ms
        self.closed = False

    @classmethod
    def is_available(cls) -> bool:
        return True

    @property
    def input_format(self) -> AudioFormat:
        return self.INPUT_FORMAT

    @property
    def output_format(self) -> AudioFormat:
        return self.OUTPUT_FORMAT

    @property
    def played_frames(self) -> int:
        return 0

    async def start(self) -> None:
        raise AudioDeviceError("voice processing failed")

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_sounddevice(monkeypatch: pytest.MonkeyPatch) -> _FakeSoundDevice:
    fake = _FakeSoundDevice()
    monkeypatch.setattr(portaudio_module, "sd", fake)
    return fake


def _pcm(frames: int, value: int = 1) -> bytes:
    return value.to_bytes(2, "little", signed=True) * frames


def _audio(**kwargs: Any) -> LocalAudio:
    return LocalAudio(
        input_sample_rate=1_000,
        output_sample_rate=1_000,
        block_ms=20,
        capture_buffer_ms=40,
        **kwargs,
    )


async def _run_tasks() -> None:
    await asyncio.sleep(0)
    await asyncio.sleep(0)


async def _wait_for_thread(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, 1)


async def test_local_audio_implements_audio_io(
    fake_sounddevice: _FakeSoundDevice,
) -> None:
    audio = _audio()
    audio_io: AudioIO = audio

    assert audio_io.input_format == AudioFormat(1_000)
    assert audio_io.output_format == AudioFormat(1_000)
    assert audio_io.played_frames == 0

    await audio.start()
    await audio.start()
    await audio.close()

    assert fake_sounddevice.input_streams[0].start_calls == 1
    assert fake_sounddevice.output_streams[0].start_calls == 1


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"block_ms": 0}, "block_ms"),
        ({"capture_buffer_ms": 0}, "capture_buffer_ms"),
        ({"latency": 0.0}, "latency"),
    ],
)
async def test_local_audio_rejects_invalid_settings(
    fake_sounddevice: _FakeSoundDevice,
    kwargs: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        LocalAudio(**kwargs)


async def test_required_echo_cancellation_rejects_incompatible_formats() -> None:
    with pytest.raises(ValueError, match="16 kHz mono input"):
        LocalAudio(
            input_sample_rate=8_000,
            echo_cancellation="required",
        )


async def test_preferred_echo_cancellation_falls_back_to_portaudio(
    fake_sounddevice: _FakeSoundDevice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_module,
        "MacOSVoiceProcessingBackend",
        _FailingVoiceProcessingBackend,
    )
    audio = LocalAudio(echo_cancellation="preferred")

    await audio.start()

    assert len(fake_sounddevice.input_streams) == 1
    assert len(fake_sounddevice.output_streams) == 1
    await audio.close()


async def test_required_echo_cancellation_does_not_fall_back(
    fake_sounddevice: _FakeSoundDevice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        local_module,
        "MacOSVoiceProcessingBackend",
        _FailingVoiceProcessingBackend,
    )
    audio = LocalAudio(echo_cancellation="required")

    with pytest.raises(AudioDeviceError, match="voice processing failed"):
        await audio.start()

    assert fake_sounddevice.input_streams == []
    assert fake_sounddevice.output_streams == []


async def test_capture_yields_pcm_chunks(fake_sounddevice: _FakeSoundDevice) -> None:
    audio = _audio()
    await audio.start()
    capture = audio.capture()

    fake_sounddevice.input_streams[0].emit(_pcm(20, 7))
    chunk = await anext(capture)

    assert chunk == AudioChunk(_pcm(20, 7), AudioFormat(1_000))

    await capture.aclose()
    await audio.close()


async def test_capture_allows_only_one_consumer(
    fake_sounddevice: _FakeSoundDevice,
) -> None:
    audio = _audio()
    await audio.start()
    first_capture = audio.capture()
    pending_chunk = asyncio.ensure_future(anext(first_capture))
    await _run_tasks()

    with pytest.raises(AudioStateError, match="only one consumer"):
        await anext(audio.capture())

    await audio.close()
    with pytest.raises(StopAsyncIteration):
        await pending_chunk


async def test_capture_drops_oldest_chunks_when_full(
    fake_sounddevice: _FakeSoundDevice,
) -> None:
    audio = _audio()
    await audio.start()

    input_stream = fake_sounddevice.input_streams[0]
    input_stream.emit(_pcm(20, 1))
    input_stream.emit(_pcm(20, 2))
    input_stream.emit(_pcm(20, 3))
    await _run_tasks()

    capture = audio.capture()
    assert (await anext(capture)).data == _pcm(20, 2)
    assert (await anext(capture)).data == _pcm(20, 3)

    await capture.aclose()
    await audio.close()


async def test_capture_reports_unexpected_input_stop(
    fake_sounddevice: _FakeSoundDevice,
) -> None:
    audio = _audio()
    await audio.start()
    capture = audio.capture()
    pending_chunk = asyncio.ensure_future(anext(capture))
    await _run_tasks()

    fake_sounddevice.input_streams[0].finish_unexpectedly()

    with pytest.raises(AudioDeviceError, match="input stream stopped unexpectedly"):
        await pending_chunk
    with pytest.raises(AudioDeviceError, match="input stream stopped unexpectedly"):
        await anext(audio.capture())
    await audio.close()


async def test_write_rejects_wrong_output_format(
    fake_sounddevice: _FakeSoundDevice,
) -> None:
    audio = _audio()
    await audio.start()

    with pytest.raises(AudioFormatError, match="Playback requires"):
        await audio.write(AudioChunk(_pcm(20), AudioFormat(2_000)))

    await audio.close()


async def test_write_splits_audio_into_short_device_blocks(
    fake_sounddevice: _FakeSoundDevice,
) -> None:
    audio = _audio()
    await audio.start()
    output = fake_sounddevice.output_streams[0]

    await audio.write(AudioChunk(_pcm(45, 3), audio.output_format))

    assert output.writes == [_pcm(20, 3), _pcm(20, 3), _pcm(5, 3)]
    assert audio.played_frames == 45
    await audio.close()


async def test_write_accepts_empty_audio(fake_sounddevice: _FakeSoundDevice) -> None:
    audio = _audio()
    await audio.start()

    await audio.write(AudioChunk(b"", audio.output_format))

    assert fake_sounddevice.output_streams[0].writes == []
    await audio.close()


async def test_write_reports_device_errors(fake_sounddevice: _FakeSoundDevice) -> None:
    audio = _audio()
    await audio.start()
    fake_sounddevice.output_streams[0].fail_write = True

    with pytest.raises(AudioDeviceError, match="Unable to play"):
        await audio.write(AudioChunk(_pcm(20), audio.output_format))

    await audio.close()


async def test_interrupt_stops_remaining_old_audio(
    fake_sounddevice: _FakeSoundDevice,
) -> None:
    audio = _audio()
    await audio.start()
    output = fake_sounddevice.output_streams[0]
    output.pause_writes()

    old_write = asyncio.create_task(
        audio.write(AudioChunk(_pcm(60, 1), audio.output_format))
    )
    await _wait_for_thread(output.write_started)
    interrupting = asyncio.create_task(audio.interrupt_playback())
    await _run_tasks()
    assert not interrupting.done()

    output.resume_writes()
    await old_write
    await interrupting
    await audio.write(AudioChunk(_pcm(20, 2), audio.output_format))

    assert output.writes == [_pcm(20, 1), _pcm(20, 2)]
    assert audio.played_frames == 40
    assert output.abort_calls == 1
    assert output.start_calls == 2
    await audio.close()


async def test_interrupt_reports_device_errors(
    fake_sounddevice: _FakeSoundDevice,
) -> None:
    audio = _audio()
    await audio.start()
    fake_sounddevice.output_streams[0].fail_abort = True

    with pytest.raises(AudioDeviceError, match="Unable to interrupt"):
        await audio.interrupt_playback()

    await audio.close()


async def test_close_unblocks_capture_and_is_idempotent(
    fake_sounddevice: _FakeSoundDevice,
) -> None:
    audio = _audio()
    await audio.start()
    capture = audio.capture()
    pending_chunk = asyncio.ensure_future(anext(capture))
    await _run_tasks()

    await audio.close()

    with pytest.raises(StopAsyncIteration):
        await pending_chunk
    await audio.close()
    assert fake_sounddevice.input_streams[0].close_calls == 1
    assert fake_sounddevice.output_streams[0].close_calls == 1


async def test_start_after_close_is_rejected(
    fake_sounddevice: _FakeSoundDevice,
) -> None:
    audio = _audio()
    await audio.close()

    with pytest.raises(AudioStateError, match="already been closed"):
        await audio.start()


async def test_close_rejects_a_writer_waiting_behind_an_active_write(
    fake_sounddevice: _FakeSoundDevice,
) -> None:
    audio = _audio()
    await audio.start()
    output = fake_sounddevice.output_streams[0]
    output.pause_writes()

    active_write = asyncio.create_task(
        audio.write(AudioChunk(_pcm(20), audio.output_format))
    )
    await _wait_for_thread(output.write_started)
    waiting_write = asyncio.create_task(
        audio.write(AudioChunk(_pcm(20), audio.output_format))
    )
    closing = asyncio.create_task(audio.close())
    await _run_tasks()

    output.resume_writes()
    await active_write
    await closing
    with pytest.raises(AudioStateError, match="closed"):
        await waiting_write


async def test_start_failure_closes_partial_resources(
    fake_sounddevice: _FakeSoundDevice,
) -> None:
    fake_sounddevice.fail_output_start = True
    audio = _audio()

    with pytest.raises(AudioDeviceError, match="Unable to start"):
        await audio.start()

    assert fake_sounddevice.input_streams[0].close_calls == 1
    assert fake_sounddevice.output_streams[0].close_calls == 1


async def test_close_reports_errors_after_releasing_both_streams(
    fake_sounddevice: _FakeSoundDevice,
) -> None:
    audio = _audio()
    await audio.start()
    fake_sounddevice.input_streams[0].fail_stop = True

    with pytest.raises(AudioDeviceError, match="Unable to close"):
        await audio.close()

    assert fake_sounddevice.input_streams[0].close_calls == 1
    assert fake_sounddevice.output_streams[0].close_calls == 1


async def test_operations_require_a_running_audio_device(
    fake_sounddevice: _FakeSoundDevice,
) -> None:
    audio = _audio()

    with pytest.raises(AudioStateError, match="not been started"):
        await audio.write(AudioChunk(_pcm(20), audio.output_format))
    with pytest.raises(AudioStateError, match="not been started"):
        await anext(audio.capture())
