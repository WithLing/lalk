import asyncio
import json
from pathlib import Path

import pytest

import lalk.tts.qwen_audio as module
from lalk.audio import AudioChunk
from lalk.tts import QwenAudioTTS, TTSError, TTSStateError, TTSTextMark

pytestmark = pytest.mark.asyncio


class Socket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.fail = False
        self.ignore_cancel = False
        self.text_sent = asyncio.Event()

    def event(self, event, **payload):
        self.incoming.put_nowait(
            json.dumps(
                {
                    "header": {"event": event, "task_id": self.task_id},
                    "payload": payload,
                }
            )
        )

    async def send(self, raw):
        msg = json.loads(raw)
        self.sent.append(msg)
        self.task_id = msg["header"]["task_id"]
        action = msg["header"]["action"]
        if action == "run-task":
            self.event("task-started")
            if self.fail:
                self.incoming.put_nowait(
                    json.dumps(
                        {
                            "header": {
                                "event": "task-failed",
                                "task_id": self.task_id,
                                "error_code": "Model.AccessDenied",
                                "error_message": "denied",
                            },
                            "payload": {},
                        }
                    )
                )
        elif action == "continue-task":
            self.text_sent.set()
        elif action == "finish-task":
            if msg["payload"]["input"].get("directive") == "cancel":
                if not self.ignore_cancel:
                    self.incoming.put_nowait(b"\x00\x00")
                    self.event("task-finished")
                return
            # Observed protocol: global time/index, punctuation within word text,
            # repeated cumulative words, usage absent in task-finished.
            for index, words, usage in [
                (
                    0,
                    [
                        {
                            "text": "，欢",
                            "begin_index": 2,
                            "end_index": 3,
                            "begin_time": 496,
                        }
                    ],
                    22,
                ),
                (
                    1,
                    [
                        {
                            "text": "今",
                            "begin_index": 10,
                            "end_index": 11,
                            "begin_time": 2610,
                        }
                    ],
                    54,
                ),
            ]:
                for _ in range(2):
                    self.event(
                        "result-generated",
                        output={
                            "type": "sentence-synthesis",
                            "sentence": {"index": index, "words": words},
                        },
                    )
                self.incoming.put_nowait(b"\x01")
                self.incoming.put_nowait(b"\x00\x02\x00")
                self.event(
                    "result-generated",
                    output={
                        "type": "sentence-end",
                        "sentence": {"index": index, "words": words},
                        "original_text": "ignored fallback",
                    },
                    usage={"characters": usage},
                )
            self.event(
                "result-generated",
                output={
                    "type": "sentence-end",
                    "sentence": {"index": 2, "words": []},
                    "original_text": "句末。",
                },
            )
            self.event("task-finished")

    async def recv(self):
        return await self.incoming.get()

    async def close(self):
        self.closed = True


@pytest.fixture
def sockets(monkeypatch):
    connections = []

    async def connect(url, **kwargs):
        socket = Socket()
        socket.url = url
        connections.append(socket)
        return socket

    monkeypatch.setattr(module.websockets, "connect", connect)
    return connections


async def test_streaming_marks_usage_and_reuse(sockets):
    async with QwenAudioTTS(api_key="test") as tts:
        for _ in range(2):

            async def parts():
                yield "你好，"
                yield ""
                yield " 欢迎。"

            stream = tts.synthesize(parts())
            items = [item async for item in stream]
            assert [item for item in items if isinstance(item, TTSTextMark)] == [
                TTSTextMark("，欢", 23808),
                TTSTextMark("今", 125280),
                TTSTextMark("句末。", 4),
            ]
            assert (
                b"".join(i.data for i in items if isinstance(i, AudioChunk))
                == b"\x01\x00\x02\x00" * 2
            )
            result = await stream.result()
            assert result.completed
            assert result.audio_bytes == 8
            assert result.input_characters == 7
            assert result.provider_usage == {"characters": 54}
        assert len(sockets) == 1
        assert sockets[0].url == "wss://dashscope.aliyuncs.com/api-ws/v1/inference"
        params = sockets[0].sent[0]["payload"]["parameters"]
        assert params["word_timestamp_enabled"] is True
    assert sockets[0].closed


async def test_cancel_drains_old_audio_and_reuses(sockets):
    async with QwenAudioTTS(api_key="test", workspace_id="workspace") as tts:
        assert "workspace.cn-beijing" in sockets[0].url

        async def parts():
            yield "hello"
            await asyncio.Event().wait()

        stream = tts.synthesize(parts())
        await sockets[0].text_sent.wait()
        await stream.aclose()
        assert not (await stream.result()).completed
        assert not sockets[0].closed
        assert sockets[0].incoming.empty()
        next_stream = tts.synthesize("next")
        assert [i async for i in next_stream]
        assert (await next_stream.result()).completed
        assert len(sockets) == 1


async def test_cancel_timeout_reconnects(sockets, monkeypatch):
    monkeypatch.setattr(module, "_CANCEL_TIMEOUT", 0.01)
    async with QwenAudioTTS(api_key="test") as tts:
        sockets[0].ignore_cancel = True

        async def parts():
            yield "hello"
            await asyncio.Event().wait()

        stream = tts.synthesize(parts())
        await sockets[0].text_sent.wait()
        await stream.aclose()
        assert sockets[0].closed
        next_stream = tts.synthesize("next")
        assert [i async for i in next_stream]
        assert len(sockets) == 2


async def test_failure_after_started(sockets):
    async with QwenAudioTTS(api_key="test") as tts:
        sockets[0].fail = True
        stream = tts.synthesize("hello")
        with pytest.raises(TTSError, match="Model.AccessDenied"):
            _ = [i async for i in stream]
        assert sockets[0].closed


async def test_input_failure_and_active_slot(sockets):
    tts = QwenAudioTTS(api_key="test")
    with pytest.raises(TTSStateError):
        tts.synthesize("hello")
    async with tts:

        async def broken():
            yield "hello"
            raise ValueError("source failed")

        stream = tts.synthesize(broken())
        with pytest.raises(TTSStateError):
            tts.synthesize("busy")
        with pytest.raises(TTSError, match="source failed"):
            _ = [i async for i in stream]


async def test_long_text_split_preserves_spaces(sockets):
    async with QwenAudioTTS(api_key="test") as tts:
        text = " x" * 11000
        stream = tts.synthesize(text)
        _ = [i async for i in stream]
        parts = [
            m["payload"]["input"]["text"]
            for m in sockets[0].sent
            if m["header"]["action"] == "continue-task"
        ]
        assert "".join(parts) == text
        assert [len(p) for p in parts] == [20000, 2000]


async def test_stalled_receiver_times_out(sockets, monkeypatch):
    monkeypatch.setattr(module, "_RESPONSE_TIMEOUT", 0.01)
    async with QwenAudioTTS(api_key="test") as tts:

        async def parts():
            yield "hello"
            await asyncio.Event().wait()

        stream = tts.synthesize(parts())
        with pytest.raises(TTSError):
            _ = [i async for i in stream]
        assert sockets[0].closed


async def test_recorded_two_sentence_response(sockets):
    records = json.loads(
        (Path(__file__).parent / "fixtures/qwen_audio_response.json").read_text()
    )
    async with QwenAudioTTS(api_key="test") as tts:
        socket = sockets[0]
        original_send = socket.send

        async def send(raw):
            message = json.loads(raw)
            if message["header"]["action"] != "finish-task":
                await original_send(raw)
                return
            for record in records:
                if record["event"] == "task-started":
                    continue
                if record["audio_bytes_before"]:
                    socket.incoming.put_nowait(bytes(record["audio_bytes_before"]))
                socket.event(record["event"], **record["payload"])

        socket.send = send
        text = "你好，欢迎使用语音助手。今天天气不错，我们一起出去走走吧。"
        stream = tts.synthesize(text)
        items = [item async for item in stream]
        marks = [item for item in items if isinstance(item, TTSTextMark)]
        assert "".join(mark.text for mark in marks) == text
        assert next(mark.at_frame for mark in marks if mark.text == "今") == 125280
        assert len(marks) == 26
        result = await stream.result()
        assert result.audio_bytes == 516480
        assert result.provider_usage == {"characters": 54}
        assert result.completed
