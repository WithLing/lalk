import asyncio
import json
from typing import Any

import pytest

import lalk.asr.qwen_audio as asr_module
from lalk.asr import (
    ASR,
    ASRError,
    ASRFormatError,
    ASRResult,
    ASRStateError,
    QwenAudioASR,
    Transcript,
)
from lalk.audio import AudioChunk, AudioFormat

pytestmark = pytest.mark.asyncio

_FORMAT = AudioFormat(16_000)


def _event(
    event: str,
    task_id: str,
    *,
    payload: dict[str, Any] | None = None,
    **header: Any,
) -> str:
    return json.dumps(
        {
            "header": {
                "event": event,
                "task_id": task_id,
                **header,
            },
            "payload": payload or {},
        },
        ensure_ascii=False,
    )


def _result(
    task_id: str,
    *,
    sentence_id: int,
    text: str,
    is_final: bool,
    duration: int | None = None,
    heartbeat: bool = False,
) -> str:
    return _event(
        "result-generated",
        task_id,
        payload={
            "output": {
                "sentence": {
                    "sentence_id": sentence_id,
                    "text": text,
                    "sentence_end": is_final,
                    "heartbeat": heartbeat,
                }
            },
            "usage": {"duration": duration} if duration is not None else None,
        },
    )


class _FakeWebSocket:
    def __init__(self) -> None:
        self.incoming: asyncio.Queue[str | bytes] = asyncio.Queue()
        self.sent: list[str | bytes] = []
        self.closed = False
        self.fail_task = False
        self.connect_kwargs: dict[str, Any] = {}
        self.connect_url = ""
        self.connect_count = 0
        self._task_id = ""
        self._results_sent = False

    async def send(self, message: str | bytes) -> None:
        self.sent.append(message)
        if isinstance(message, bytes):
            if self._results_sent:
                return
            self._results_sent = True
            self.incoming.put_nowait(
                _result(
                    self._task_id,
                    sentence_id=1,
                    text="你",
                    is_final=False,
                )
            )
            self.incoming.put_nowait(
                _result(
                    self._task_id,
                    sentence_id=1,
                    text="你好",
                    is_final=True,
                    duration=2,
                )
            )
            self.incoming.put_nowait(
                _result(
                    self._task_id,
                    sentence_id=2,
                    text="你好",
                    is_final=True,
                    duration=3,
                )
            )
            self.incoming.put_nowait(
                _result(
                    self._task_id,
                    sentence_id=3,
                    text="",
                    is_final=True,
                    duration=4,
                )
            )
            return

        request = json.loads(message)
        header = request["header"]
        action = header["action"]
        self._task_id = header["task_id"]
        if action == "run-task":
            self._results_sent = False
            if self.fail_task:
                self.incoming.put_nowait(
                    _event(
                        "task-failed",
                        self._task_id,
                        error_code="CLIENT_ERROR",
                        error_message="invalid request",
                    )
                )
            else:
                self.incoming.put_nowait(_event("task-started", self._task_id))
        elif action == "finish-task":
            self.incoming.put_nowait(_event("task-finished", self._task_id))

    async def recv(self) -> str | bytes:
        return await self.incoming.get()

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_websocket(monkeypatch: pytest.MonkeyPatch) -> _FakeWebSocket:
    websocket = _FakeWebSocket()

    async def connect(*args: Any, **kwargs: Any) -> _FakeWebSocket:
        websocket.connect_count += 1
        websocket.connect_url = args[0]
        websocket.connect_kwargs = kwargs
        return websocket

    monkeypatch.setattr(asr_module.websockets, "connect", connect)
    return websocket


def _asr() -> QwenAudioASR:
    return QwenAudioASR(api_key="api-key", workspace_id="workspace-id")


async def test_streams_pcm_transcripts_and_billable_usage(
    fake_websocket: _FakeWebSocket,
) -> None:
    asr: ASR = _asr()
    await asr.start(_FORMAT)
    stream = asr.recognize()
    collecting = asyncio.create_task(
        _collect(stream),
    )

    chunk = AudioChunk(b"\x01\x00" * 320, _FORMAT)
    for _ in range(5):
        await stream.write(chunk)
    await stream.finish()

    assert await collecting == [
        Transcript("你", is_final=False),
        Transcript("你好"),
        Transcript("你好"),
    ]
    assert await stream.result() == ASRResult(
        input_audio_seconds=0.1,
        output_characters=4,
        completed=True,
        provider_usage={"duration": 4},
    )

    run_task = json.loads(
        next(
            message
            for message in fake_websocket.sent
            if isinstance(message, str)
        )
    )
    parameters = run_task["payload"]["parameters"]
    assert run_task["payload"]["model"] == "qwen-audio-3.0-asr-flash-streaming"
    assert parameters == {
        "format": "pcm",
        "sample_rate": 16_000,
        "semantic_punctuation_enabled": False,
    }
    assert [
        message for message in fake_websocket.sent if isinstance(message, bytes)
    ] == [chunk.data * 5]

    finish_task = json.loads(
        [message for message in fake_websocket.sent if isinstance(message, str)][-1]
    )
    assert finish_task["header"]["action"] == "finish-task"
    assert finish_task["header"]["task_id"] == run_task["header"]["task_id"]
    await asr.close()


async def test_uses_workspace_endpoint_and_bearer_auth(
    fake_websocket: _FakeWebSocket,
) -> None:
    asr = _asr()
    await asr.start(_FORMAT)

    assert fake_websocket.connect_kwargs["additional_headers"] == {
        "Authorization": "Bearer api-key",
        "user-agent": "lalk",
    }
    await asr.close()
    assert fake_websocket.closed


async def test_reuses_connection_for_sequential_streams(
    fake_websocket: _FakeWebSocket,
) -> None:
    asr = _asr()
    await asr.start(_FORMAT)

    for _ in range(2):
        stream = asr.recognize()
        collecting = asyncio.create_task(_collect(stream))
        await stream.write(AudioChunk(b"\x00\x00" * 1_600, _FORMAT))
        await stream.finish()
        await collecting

    run_tasks = [
        json.loads(message)
        for message in fake_websocket.sent
        if isinstance(message, str)
        and json.loads(message)["header"]["action"] == "run-task"
    ]
    assert len(run_tasks) == 2
    assert fake_websocket.connect_count == 1
    await asr.close()


async def test_sends_optional_server_vad_and_noise_parameters(
    fake_websocket: _FakeWebSocket,
) -> None:
    asr = QwenAudioASR(
        api_key="api-key",
        workspace_id="workspace-id",
        speech_noise_threshold=0.2,
        max_sentence_silence_ms=800,
        heartbeat=True,
    )
    await asr.start(_FORMAT)
    stream = asr.recognize()
    collecting = asyncio.create_task(_collect(stream))
    await stream.write(AudioChunk(b"\x00\x00" * 1_600, _FORMAT))
    await stream.finish()
    await collecting

    run_task = json.loads(
        next(
            message
            for message in fake_websocket.sent
            if isinstance(message, str)
        )
    )
    assert run_task["payload"]["parameters"] == {
        "format": "pcm",
        "sample_rate": 16_000,
        "semantic_punctuation_enabled": False,
        "speech_noise_threshold": 0.2,
        "max_sentence_silence": 800,
        "heartbeat": True,
    }
    await asr.close()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"api_key": " "}, "api_key"),
        ({"model": " "}, "model"),
    ],
)
async def test_rejects_empty_configuration(
    kwargs: dict[str, str],
    message: str,
) -> None:
    settings = {
        "api_key": "api-key",
        "workspace_id": "workspace-id",
        **kwargs,
    }
    with pytest.raises(ValueError, match=message):
        QwenAudioASR(**settings)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"speech_noise_threshold": -1.1}, "speech_noise_threshold"),
        ({"speech_noise_threshold": 1.1}, "speech_noise_threshold"),
        ({"max_sentence_silence_ms": 199}, "max_sentence_silence_ms"),
        ({"max_sentence_silence_ms": 6_001}, "max_sentence_silence_ms"),
    ],
)
async def test_rejects_invalid_server_vad_configuration(
    kwargs: dict[str, float | int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        QwenAudioASR(api_key="api-key", **kwargs)


@pytest.mark.parametrize(
    ("workspace_id", "expected_url"),
    [
        (None, "wss://dashscope.aliyuncs.com/api-ws/v1/inference"),
        (" ", "wss://dashscope.aliyuncs.com/api-ws/v1/inference"),
        (
            "workspace-id",
            "wss://workspace-id.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference",
        ),
    ],
)
async def test_selects_endpoint_for_optional_workspace(
    fake_websocket: _FakeWebSocket,
    workspace_id: str | None,
    expected_url: str,
) -> None:
    asr = QwenAudioASR(api_key="api-key", workspace_id=workspace_id)

    await asr.start(_FORMAT)

    assert fake_websocket.connect_url == expected_url
    await asr.close()


async def test_requires_16_khz_mono_pcm() -> None:
    asr = _asr()
    with pytest.raises(ASRFormatError):
        await asr.start(AudioFormat(48_000))
    await asr.close()


async def test_requires_start_and_one_active_stream(
    fake_websocket: _FakeWebSocket,
) -> None:
    asr = _asr()
    with pytest.raises(ASRStateError, match="not been started"):
        asr.recognize()

    await asr.start(_FORMAT)
    stream = asr.recognize()
    with pytest.raises(ASRStateError, match="one active"):
        asr.recognize()
    await stream.aclose()
    await asr.close()


async def test_surfaces_provider_task_failures(
    fake_websocket: _FakeWebSocket,
) -> None:
    fake_websocket.fail_task = True
    asr = _asr()
    await asr.start(_FORMAT)
    stream = asr.recognize()
    await stream.write(AudioChunk(b"\x00\x00" * 320, _FORMAT))

    with pytest.raises(ASRError, match="invalid request"):
        await stream.finish()

    await stream.aclose()
    await asr.close()


async def _collect(stream: Any) -> list[Transcript]:
    return [transcript async for transcript in stream]
