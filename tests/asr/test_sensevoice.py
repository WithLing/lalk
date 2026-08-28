import asyncio
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from lalk.asr import (
    ASR,
    ASRError,
    ASRFormatError,
    ASRResult,
    ASRStateError,
    SenseVoiceASR,
    Transcript,
)
from lalk.audio import AudioChunk, AudioFormat

pytestmark = pytest.mark.asyncio

_FORMAT = AudioFormat(16_000)


class _FakeResult:
    def __init__(self, text: str = " 你好 ", language: str = "<|zh|>") -> None:
        self.text = text
        self.lang = language


class _FakeStream:
    def __init__(self, result: _FakeResult) -> None:
        self.result = result
        self.samples: np.ndarray[Any, Any] | None = None

    def accept_waveform(
        self,
        sample_rate: int,
        samples: np.ndarray[Any, Any],
    ) -> None:
        assert sample_rate == _FORMAT.sample_rate
        self.samples = samples.copy()


class _FakeRecognizer:
    def __init__(self, result: _FakeResult | None = None) -> None:
        self.result = result or _FakeResult()
        self.streams: list[_FakeStream] = []
        self.error: Exception | None = None

    def create_stream(self) -> _FakeStream:
        stream = _FakeStream(self.result)
        self.streams.append(stream)
        return stream

    def decode_stream(self, stream: _FakeStream) -> None:
        if self.error is not None:
            raise self.error


def _install_recognizer(
    monkeypatch: pytest.MonkeyPatch,
    recognizer: _FakeRecognizer | None = None,
) -> _FakeRecognizer:
    recognizer = recognizer or _FakeRecognizer()
    monkeypatch.setattr(
        SenseVoiceASR,
        "_resolve_model_files",
        lambda _self: (Path("model.onnx"), Path("tokens.txt")),
    )
    monkeypatch.setattr(
        SenseVoiceASR,
        "_load_model",
        lambda _self, _model, _tokens: recognizer,
    )
    return recognizer


def _chunk(data: bytes = b"\x00\x40\x00\xc0") -> AudioChunk:
    return AudioChunk(data, _FORMAT)


async def _recognize(
    asr: ASR,
    audio: AudioChunk,
) -> tuple[list[Transcript], ASRResult]:
    stream = asr.recognize()
    await stream.write(audio)
    await stream.finish()
    transcripts = [transcript async for transcript in stream]
    return transcripts, await stream.result()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"threads": 0}, "threads"),
        ({"language": "invalid"}, "language"),
    ],
)
async def test_rejects_invalid_configuration(
    kwargs: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        SenseVoiceASR(model_dir="model", **kwargs)


async def test_implements_asr_protocol_and_normalizes_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recognizer = _install_recognizer(monkeypatch)
    asr: ASR = SenseVoiceASR(model_dir="model")
    await asr.start(_FORMAT)

    transcripts, result = await _recognize(asr, _chunk())

    assert transcripts == [Transcript(text="你好", language="zh")]
    assert result == ASRResult(
        input_audio_seconds=0.000125,
        output_characters=2,
        completed=True,
    )
    assert recognizer.streams[0].samples is not None
    assert recognizer.streams[0].samples.tolist() == [0.5, -0.5]
    await asr.close()


async def test_releases_completed_stream_for_sequential_recognition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recognizer = _install_recognizer(monkeypatch)
    asr: ASR = SenseVoiceASR(model_dir="model")
    await asr.start(_FORMAT)

    for _ in range(2):
        transcripts, result = await _recognize(asr, _chunk())
        assert transcripts == [Transcript(text="你好", language="zh")]
        assert result.completed

    assert len(recognizer.streams) == 2
    await asr.close()


async def test_empty_audio_does_not_create_a_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recognizer = _install_recognizer(monkeypatch)
    asr = SenseVoiceASR(model_dir="model")
    await asr.start(_FORMAT)

    transcripts, result = await _recognize(asr, _chunk(b""))

    assert transcripts == []
    assert result == ASRResult(0.0, 0, True)
    assert recognizer.streams == []
    await asr.close()


async def test_requires_16_khz_mono_audio() -> None:
    asr = SenseVoiceASR(model_dir="model")

    with pytest.raises(ASRFormatError):
        await asr.start(AudioFormat(48_000))

    await asr.close()


async def test_resolves_one_model_and_tokens_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model = tmp_path / "model.int8.onnx"
    tokens = tmp_path / "tokens.txt"
    model.write_bytes(b"model")
    tokens.write_text("tokens")
    received: list[tuple[Path, Path]] = []
    monkeypatch.setattr(
        SenseVoiceASR,
        "_load_model",
        lambda _self, model_path, tokens_path: (
            received.append((model_path, tokens_path)) or _FakeRecognizer()
        ),
    )
    asr = SenseVoiceASR(model_dir=tmp_path)

    await asr.start(_FORMAT)

    assert received == [(model, tokens)]
    await asr.close()


@pytest.mark.parametrize("layout", ["missing", "no-model", "two-models", "no-tokens"])
async def test_reports_invalid_model_directories(tmp_path: Path, layout: str) -> None:
    model_dir = tmp_path / "sensevoice"
    if layout != "missing":
        model_dir.mkdir()
    if layout in {"two-models", "no-tokens"}:
        (model_dir / "model.onnx").write_bytes(b"model")
    if layout == "two-models":
        (model_dir / "other.onnx").write_bytes(b"model")
    if layout in {"no-model", "two-models"}:
        (model_dir / "tokens.txt").write_text("tokens")
    asr = SenseVoiceASR(model_dir=model_dir)

    with pytest.raises(ASRError):
        await asr.start(_FORMAT)

    await asr.close()


async def test_reports_model_load_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_recognizer(monkeypatch)

    def fail_load(_self: SenseVoiceASR, _model: Path, _tokens: Path) -> None:
        raise RuntimeError("load failed")

    monkeypatch.setattr(SenseVoiceASR, "_load_model", fail_load)
    asr = SenseVoiceASR(model_dir="model")

    with pytest.raises(ASRError, match="Unable to load"):
        await asr.start(_FORMAT)

    await asr.close()


async def test_reports_inference_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    recognizer = _install_recognizer(monkeypatch)
    recognizer.error = RuntimeError("decode failed")
    asr = SenseVoiceASR(model_dir="model")
    await asr.start(_FORMAT)
    stream = asr.recognize()
    await stream.write(_chunk())

    with pytest.raises(ASRError, match="Unable to transcribe"):
        await stream.finish()

    await asr.close()


async def test_inference_does_not_block_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()

    class BlockingRecognizer(_FakeRecognizer):
        def decode_stream(self, stream: _FakeStream) -> None:
            started.set()
            if not release.wait(timeout=2):
                raise RuntimeError("test inference timed out")

    _install_recognizer(monkeypatch, BlockingRecognizer())
    asr = SenseVoiceASR(model_dir="model")
    await asr.start(_FORMAT)
    stream = asr.recognize()
    await stream.write(_chunk())

    transcribing = asyncio.create_task(stream.finish())
    assert await asyncio.to_thread(started.wait, 1)
    await asyncio.sleep(0)
    assert not transcribing.done()

    release.set()
    await transcribing
    assert [transcript async for transcript in stream] == [
        Transcript(text="你好", language="zh")
    ]
    await asr.close()


async def test_close_is_idempotent_and_prevents_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_recognizer(monkeypatch)
    asr = SenseVoiceASR(model_dir="model")

    await asr.close()
    await asr.close()

    with pytest.raises(ASRStateError, match="already been closed"):
        await asr.start(_FORMAT)
